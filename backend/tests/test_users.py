from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_accounts import PASSWORD
from test_accounts import accounts as accounts
from test_api_write import api as api
from test_auth_sessions_api import client as client
from test_auth_sessions_api import headers, login
from test_sessions import session_env as session_env

from app.models import AuditEvent, AuthSession, User

TEMP = "temporary password 123"


def create(client, pair, name="second"):
    return client.post("/api/v1/users", headers=headers(pair), json={"username": name, "password": TEMP, "display_name": "Other admin"})


def test_users_require_authentication_and_safe_immutable_dto(client):
    assert client.get("/api/v1/users").status_code == 401
    assert client.post("/api/v1/users", json={"username": "other", "password": TEMP}).status_code == 401
    pair = login(client)
    response = create(client, pair)
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["is_local"] and user["must_change_password"] and user["active"]
    assert "password_hash" not in response.text and TEMP not in response.text
    assert client.patch(f"/api/v1/users/{user['id']}", headers=headers(pair), json={"username": "renamed"}).status_code == 422
    assert client.delete(f"/api/v1/users/{user['id']}", headers=headers(pair)).status_code == 405
    assert len(client.get("/api/v1/users", headers=headers(pair)).json()) == 2


def test_temporary_password_allows_only_me_change_and_logout(client):
    pair = login(client)
    create(client, pair)
    response = client.post("/api/v1/auth/token", json={"username": "second", "password": TEMP})
    assert response.status_code == 200
    temporary = response.json()
    assert temporary["must_change_password"] and temporary["user"]["must_change_password"]
    assert client.get("/api/v1/auth/me", headers=headers(temporary)).status_code == 200
    for method, route in [("get", "users"), ("get", "jobs"), ("get", "settings"), ("get", "telegram/login"), ("post", "auth/activity"), ("post", "auth/revoke-all")]:
        assert getattr(client, method)(f"/api/v1/{route}", headers=headers(temporary)).status_code == 403
    logout_pair = client.post("/api/v1/auth/token", json={"username": "second", "password": TEMP}).json()
    assert client.post("/api/v1/auth/logout", headers=headers(logout_pair)).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": temporary["refresh_token"]}).status_code == 403
    assert client.post("/api/v1/auth/change-password", headers=headers(temporary), json={"current_password": "wrong password", "new_password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/change-password", headers=headers(temporary), json={"current_password": TEMP, "new_password": PASSWORD}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers(temporary)).status_code == 401
    fresh = client.post("/api/v1/auth/token", json={"username": "second", "password": PASSWORD}).json()
    assert not fresh["must_change_password"]
    assert client.get("/api/v1/users", headers=headers(fresh)).status_code == 200


def test_reset_disable_revoke_and_audit(client, test_engine):
    pair = login(client)
    user = create(client, pair).json()
    other = client.post("/api/v1/auth/token", json={"username": "second", "password": TEMP}).json()
    url = f"/api/v1/users/{user['id']}"
    assert client.post(url + "/reset-password", headers=headers(pair), json={"password": PASSWORD}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers(other)).status_code == 401
    other = client.post("/api/v1/auth/token", json={"username": "second", "password": PASSWORD}).json()
    assert client.post(url + "/revoke-sessions", headers=headers(pair)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers(other)).status_code == 401
    assert client.patch(url, headers=headers(pair), json={"active": False}).status_code == 200
    assert client.post("/api/v1/auth/token", json={"username": "second", "password": PASSWORD}).status_code == 401
    with Session(test_engine) as db:
        events = list(db.scalars(select(AuditEvent)))
        assert {"user.create", "user.reset_password", "user.revoke_sessions", "user.update", "auth.login"} <= {e.action for e in events}
        assert any(e.action == "auth.login" and e.outcome == "failure" for e in events)
        assert all(e.created_at.utcoffset().total_seconds() == 0 for e in events)
        assert TEMP not in str([(e.action, e.target_id, e.outcome) for e in events])
        assert all(s.revoked_at is not None for s in db.scalars(select(AuthSession).where(AuthSession.user_id == UUID(user["id"]))))


def test_last_local_admin_protected_even_with_external_account(client, test_engine):
    pair = login(client)
    with Session(test_engine) as db:
        db.add(User(username="external", password_hash=None, active=True))
        db.commit()
    response = client.patch(f"/api/v1/users/{pair['user']['id']}", headers=headers(pair), json={"active": False})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_local_admin"


def test_two_concurrent_deactivations_keep_one_local_admin(db_session, test_engine, accounts):
    from app.services.accounts import update_user
    from app.services.auth import AuthError

    users = [accounts.create_local_user(db_session, name, PASSWORD) for name in ("alice", "bob")]
    db_session.add(User(username="external", active=True))
    db_session.commit()
    ids = [u.id for u in users]
    barrier = Barrier(2)

    def disable(user_id):
        with Session(test_engine) as db:
            barrier.wait(timeout=5)
            try:
                update_user(db, user_id, active=False)
                db.commit()
                return "ok"
            except AuthError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(disable, ids)) == ["last_local_admin", "ok"]
    db_session.expire_all()
    assert sum(u.active for u in db_session.scalars(select(User).where(User.password_hash.is_not(None)))) == 1


@pytest.mark.parametrize("mutation", ["reset", "disable", "change"])
def test_account_mutations_hold_user_lock_and_rollback_sessions(db_session, test_engine, accounts, session_env, mutation):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.services.accounts import change_password, reset_password, update_user

    sessions, *_ = session_env
    user = accounts.create_local_user(db_session, "alice", PASSWORD)
    accounts.create_local_user(db_session, "other", PASSWORD)
    pair = sessions.issue_session(db_session, user)
    db_session.commit()
    if mutation == "reset":
        reset_password(db_session, user.id, TEMP)
    elif mutation == "disable":
        update_user(db_session, user.id, active=False)
        with Session(test_engine) as other:
            assert other.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": 0x54444C41444D494E}) is False
    else:
        change_password(db_session, user.id, PASSWORD, TEMP)
    with Session(test_engine) as other:
        other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            other.scalar(select(User).where(User.id == user.id).with_for_update())
        other.rollback()
    db_session.rollback()
    assert sessions.verify_session(db_session, pair.access_token).id == user.id
    assert accounts.verify_credentials(db_session, "alice", PASSWORD, origin="test").id == user.id


def test_external_disabled_reset_never_enables_or_converts(client, test_engine):
    pair = login(client)
    with Session(test_engine) as db:
        external = User(username="external", active=False)
        db.add(external)
        db.commit()
        target = external.id
    assert client.post(f"/api/v1/users/{target}/reset-password", headers=headers(pair), json={"password": TEMP}).status_code == 409
    with Session(test_engine) as db:
        user = db.get(User, target)
        assert not user.active and user.password_hash is None


def test_sensitive_operation_audit_outcomes_and_secret_exclusion(client, test_engine, monkeypatch):
    from types import SimpleNamespace

    from app.api.errors import ApiError
    from app.api.v1 import admin, jobs, telegram
    from app.api.v1 import settings as routes
    from app.services.jobs import QueueUnavailableError

    pair = login(client)
    auth = headers(pair)
    monkeypatch.setattr(routes, "save_settings", lambda *a: True)
    monkeypatch.setattr(routes, "read_settings", lambda *a: {})
    payload = {"downloads_dir": "/secret-path", "command_timeout_seconds": 1, "download_batch_size": 1, "download_idle_timeout_seconds": 1, "export_batch_size": 1}
    assert client.put("/api/v1/settings", headers=auth, json=payload).status_code == 202
    monkeypatch.setattr(telegram.interactive_login_service, "send", lambda value: None)
    monkeypatch.setattr(telegram, "_status", lambda: {})
    assert client.post("/api/v1/telegram/login/input", headers=auth, json={"value": "secret-telegram-code"}).status_code == 200
    monkeypatch.setattr(telegram.interactive_login_service, "start", lambda: (_ for _ in ()).throw(RuntimeError("secret-url")))
    assert client.post("/api/v1/telegram/login/start", headers=auth).status_code == 503
    monkeypatch.setattr(jobs, "get_job_or_404", lambda *a: SimpleNamespace(id=42))
    monkeypatch.setattr(jobs, "enqueue_delete", lambda *a: None)
    monkeypatch.setattr(jobs, "queue_position", lambda *a: None)
    monkeypatch.setattr(jobs, "job_read", lambda *a: (_ for _ in ()).throw(ApiError("end_test", "test", 409)))
    # Audit acceptance before response formatting, not completed asynchronous deletion.
    assert client.request("DELETE", "/api/v1/jobs/42", headers=auth, json={"confirm": True}).status_code == 409
    monkeypatch.setattr(jobs, "enqueue_delete", lambda *a: (_ for _ in ()).throw(QueueUnavailableError("secret-redis-url")))
    assert client.request("DELETE", "/api/v1/jobs/42", headers=auth, json={"confirm": True}).status_code == 503
    monkeypatch.setattr(admin, "reset_application_state", lambda *a, **k: {"redis_cleared": False})
    assert client.post("/api/v1/admin/reset", headers=auth, json={"confirmation": "REINICIAR", "keep_session": True}).status_code == 200
    with Session(test_engine) as db:
        events = [(e.action, e.target_id, e.outcome) for e in db.scalars(select(AuditEvent))]
    assert ("settings.update", None, "accepted") in events
    assert ("telegram.input", None, "accepted") in events
    assert ("telegram.start", None, "failure") in events
    assert ("job.delete", "42", "accepted") in events
    assert ("job.delete", "42", "failure") in events
    assert ("application.reset", None, "partial") in events
    assert all(secret not in str(events) for secret in ["secret-path", "secret-telegram-code", "secret-url", "secret-redis-url", PASSWORD])


def test_failed_account_mutations_and_logout_are_audited(client, test_engine):
    pair = login(client)
    create(client, pair)
    assert create(client, pair).status_code == 409
    assert client.post("/api/v1/auth/change-password", headers=headers(pair), json={"current_password": "wrong password", "new_password": TEMP}).status_code == 401
    assert client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}).status_code == 204
    with Session(test_engine) as db:
        events = {(e.action, e.outcome) for e in db.scalars(select(AuditEvent))}
    assert {("user.create", "failure"), ("auth.change_password", "failure"), ("session.revoke", "success")} <= events


def test_reset_commit_failure_restores_password_sessions_and_audit(client, test_engine, monkeypatch):
    pair = login(client)
    target = pair["user"]["id"]
    with Session(test_engine) as db:
        original_hash = db.get(User, UUID(target)).password_hash
    real_commit = Session.commit
    monkeypatch.setattr(Session, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("commit failed")))
    with pytest.raises(RuntimeError, match="commit failed"):
        client.post(f"/api/v1/users/{target}/reset-password", headers=headers(pair), json={"password": TEMP})
    monkeypatch.setattr(Session, "commit", real_commit)
    with Session(test_engine) as db:
        assert db.get(User, UUID(target)).password_hash == original_hash
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "user.reset_password")) is None
    assert client.get("/api/v1/auth/me", headers=headers(pair)).status_code == 200


def test_real_settings_delete_and_application_reset_preserve_audit(api):
    from test_api_write import WRITE_HEADERS, create_payload
    from test_runtime_settings import values

    from app.config import settings

    client, sessions, _ = api
    assert client.put("/api/v1/settings", headers=WRITE_HEADERS, json=values(settings.downloads_dir)).status_code == 200
    job = client.post("/api/v1/jobs", headers=WRITE_HEADERS, json=create_payload()).json()
    assert client.request("DELETE", f"/api/v1/jobs/{job['id']}", headers=WRITE_HEADERS, json={"confirm": True}).status_code == 202
    assert client.post("/api/v1/admin/reset", headers=WRITE_HEADERS, json={"confirmation": "REINICIAR", "keep_session": True}).status_code == 200
    with sessions() as db:
        events = {(e.action, e.outcome) for e in db.scalars(select(AuditEvent))}
    assert {("settings.update", "success"), ("job.delete", "accepted"), ("application.reset", "success")} <= events


@pytest.mark.parametrize("operations", [("reset", "reset"), ("reset", "revoke"), ("revoke", "revoke"), ("update", "reset")])
def test_reciprocal_admin_mutations_do_not_deadlock_actor_audit_fk(db_session, test_engine, accounts, monkeypatch, operations):
    from app.api.v1 import users as routes
    from app.schemas import PasswordReset, UserRead, UserUpdate

    people = [accounts.create_local_user(db_session, name, PASSWORD) for name in ("alice", "bob")]
    db_session.commit()
    ids = [user.id for user in people]
    start, locked = Barrier(2), Barrier(2)

    def synchronized(function):
        def mutate(*args, **kwargs):
            result = function(*args, **kwargs)
            try:
                locked.wait(timeout=1)
            except BrokenBarrierError:
                pass  # A serialized peer cannot own its target until this commits.
            return result
        return mutate

    for name in ("reset_password", "revoke_all_sessions", "update_user"):
        monkeypatch.setattr(routes, name, synchronized(getattr(routes, name)))

    def operate(index):
        with Session(test_engine) as db:
            start.wait(timeout=5)
            actor = UserRead(id=ids[index], username=people[index].username)
            target = ids[1 - index]
            if operations[index] == "reset":
                routes.reset_user_password(target, PasswordReset(password=TEMP), db, actor)
            elif operations[index] == "revoke":
                routes.revoke_user_sessions(target, db, actor)
            else:
                routes.patch_user(target, UserUpdate(display_name="Changed"), db, actor)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(operate, index) for index in (0, 1)]
        for future in futures:
            future.result(timeout=15)
    with Session(test_engine) as db:
        assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.outcome == "success")))) == 2


@pytest.mark.parametrize("operation", ["settings", "delete", "reset", "telegram"])
def test_legacy_action_keeps_durable_intent_if_final_audit_fails(api, monkeypatch, operation):
    from sqlalchemy.exc import SQLAlchemyError
    from test_api_write import WRITE_HEADERS, create_payload
    from test_runtime_settings import values

    from app.api.v1 import telegram
    from app.config import settings
    from app.models import DownloadJob, RuntimeSettings
    from app.services import audit as audit_service

    client, sessions, _ = api
    original = audit_service.audit
    expected_action = {"settings": "settings.update", "delete": "job.delete", "reset": "application.reset", "telegram": "telegram.input"}[operation]

    def failing_final(db, actor_id, action, target_id, outcome):
        if action == expected_action and outcome != "started":
            raise SQLAlchemyError("final audit unavailable")
        return original(db, actor_id, action, target_id, outcome)

    monkeypatch.setattr(audit_service, "audit", failing_final)
    if operation == "settings":
        monkeypatch.setattr(settings, "download_batch_size", settings.download_batch_size)
        payload = {**values(settings.downloads_dir), "download_batch_size": 777}
    elif operation == "delete":
        job = client.post("/api/v1/jobs", headers=WRITE_HEADERS, json=create_payload()).json()
    elif operation == "telegram":
        monkeypatch.setattr(telegram.interactive_login_service, "send", lambda value: None)

    def action():
        if operation == "settings":
            return client.put("/api/v1/settings", headers=WRITE_HEADERS, json=payload)
        if operation == "delete":
            return client.request("DELETE", f"/api/v1/jobs/{job['id']}", headers=WRITE_HEADERS, json={"confirm": True})
        if operation == "reset":
            return client.post("/api/v1/admin/reset", headers=WRITE_HEADERS, json={"confirmation": "REINICIAR", "keep_session": True})
        return client.post("/api/v1/telegram/login/input", headers=WRITE_HEADERS, json={"value": "private-code"})

    with pytest.raises(SQLAlchemyError, match="final audit unavailable"):
        action()
    with sessions() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == expected_action)))
        assert [event.outcome for event in events] == ["started"]
        if operation == "settings":
            assert '777' in db.get(RuntimeSettings, 1).values_json
        elif operation == "delete":
            assert db.get(DownloadJob, job["id"]).deletion_requested


def test_audit_intent_preserves_storage_lock_and_uncommitted_writes(test_engine):
    from sqlalchemy import text

    from app.models import DownloadTemplate
    from app.services.audit import audited_operation
    from app.services.runtime_settings import _STORAGE_LOCK_KEY, require_storage_available

    with Session(test_engine, autoflush=False) as db:
        require_storage_available(db)
        pending = DownloadTemplate(name="Pending")
        db.add(pending)
        with audited_operation(db, None, "settings.update"):
            with Session(test_engine) as other:
                assert other.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _STORAGE_LOCK_KEY}) is False
                assert other.scalar(select(DownloadTemplate)) is None
                assert other.scalar(select(AuditEvent).where(AuditEvent.outcome == "started")) is not None
        assert pending.id is not None


def test_reset_reports_filesystem_failure_even_when_redis_clears(api, monkeypatch):
    from test_api_write import WRITE_HEADERS

    from app.config import settings

    client, sessions, _ = api
    blocked = settings.downloads_dir / "blocked"
    blocked.mkdir()
    def cannot_remove(*args, **kwargs):
        if not kwargs.get("ignore_errors"):
            raise PermissionError("cannot remove")
    monkeypatch.setattr("app.services.admin.shutil.rmtree", cannot_remove)
    response = client.post("/api/v1/admin/reset", headers=WRITE_HEADERS, json={"confirmation": "REINICIAR", "keep_session": True})
    assert response.status_code == 200
    assert response.json()["redis_cleared"] and not response.json()["filesystem_cleared"]
    assert blocked.exists()
    with sessions() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "application.reset", AuditEvent.outcome == "partial")) is not None


def test_production_engine_hides_bound_secret_on_real_sql_error(caplog):
    import logging

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.database import engine

    marker = "fake-secret-sql-parameter-marker"
    with engine.connect() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(text("SELECT :secret, 1 / 0"), {"secret": marker})
    logging.getLogger(__name__).error("Database operation failed", exc_info=(type(error.value), error.value, error.value.__traceback__))
    assert engine.hide_parameters
    assert marker not in str(error.value) and marker not in caplog.text
