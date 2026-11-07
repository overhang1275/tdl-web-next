from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import AuthSession, User
from test_accounts import PASSWORD, accounts
from test_sessions import session_env


@pytest.fixture
def client(monkeypatch, test_engine, session_env, accounts):
    monkeypatch.setattr("app.main.init_db", lambda: None)

    def database():
        with Session(test_engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = database
    with Session(test_engine) as db:
        accounts.create_local_user(db, "admin", PASSWORD)
        db.commit()
    with TestClient(app) as client:
        client.headers["X-Requested-With"] = "tdl-web"
        yield client
    app.dependency_overrides.pop(get_db, None)


def login(client):
    response = client.post("/api/v1/auth/token", json={"username": "ADMIN", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def headers(pair):
    return {"Authorization": f"Bearer {pair['access_token']}"}


def test_login_refresh_me_logout(client, test_engine):
    pair = login(client)
    assert pair["user"]["username"] == "admin"
    assert PASSWORD not in str(pair)
    assert client.get("/api/v1/auth/me", headers=headers(pair)).status_code == 200
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    successor = response.json()
    assert successor["refresh_token"] != pair["refresh_token"]
    assert client.post("/api/v1/auth/logout", headers=headers(successor)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers(successor)).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": successor["refresh_token"]}).status_code == 401


def test_api_replay_commits_revocation_before_401(client, session_env):
    sessions, clock, *_ = session_env
    original = login(client)
    result = client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert result.status_code == 200
    clock[0] += timedelta(seconds=6)
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "refresh_reused"
    assert client.get("/api/v1/auth/me", headers=headers(result.json())).status_code == 401


def test_explicit_activity_and_revoke_all(client, test_engine, session_env):
    _, clock, *_ = session_env
    pair = login(client)
    second = login(client)
    clock[0] += timedelta(seconds=60)
    assert client.post("/api/v1/auth/activity", headers=headers(pair), json={"time": "2099-01-01"}).status_code == 204
    with Session(test_engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.id == pair["session_id"]))
        assert row.last_activity_at == clock[0]
    assert client.post("/api/v1/auth/revoke-all", headers=headers(pair)).status_code == 204
    for item in (pair, second):
        assert client.get("/api/v1/auth/me", headers=headers(item)).status_code == 401


@pytest.mark.parametrize("route", ["logout", "activity", "revoke-all"])
def test_session_mutations_require_authentication(client, route):
    assert client.post(f"/api/v1/auth/{route}").status_code == 401


def test_login_origin_cannot_be_overridden(client):
    # The caller varies both untrusted headers: all attempts must share the
    # conservative peer bucket, so attempt 31 is rejected for a new account.
    for i in range(30):
        response = client.post("/api/v1/auth/token", json={"username": f"unknown{i}", "password": PASSWORD},
                               headers={"X-Forwarded-For": f"10.0.0.{i}", "X-Real-IP": f"10.0.1.{i}"})
        assert response.status_code == 401
    response = client.post("/api/v1/auth/token", json={"username": "another", "password": PASSWORD})
    assert response.status_code == 429
    assert PASSWORD not in response.text
    response = client.post("/api/v1/auth/token", json={"username": "admin", "password": PASSWORD, "origin": "fake"})
    assert response.status_code == 422
    assert PASSWORD not in response.text


def test_missing_csrf_and_no_public_registration(client):
    client.headers.pop("X-Requested-With")
    assert client.post("/api/v1/auth/token", json={"username": "admin", "password": PASSWORD}).status_code == 403
    client.headers["X-Requested-With"] = "tdl-web"
    assert client.post("/api/v1/auth/register", json={}).status_code == 404
    assert client.post("/api/v1/auth/exchange", json={}).status_code == 422


def test_redis_write_failure_is_transient_and_rolls_back_api_transaction(client, session_env, test_engine, monkeypatch):
    from redis.exceptions import ConnectionError

    sessions, _, _, redis = session_env
    original = login(client)
    original_set = redis.set

    def unavailable(*args, **kwargs):
        raise ConnectionError("unavailable")

    monkeypatch.setattr(redis, "set", unavailable)
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"
    with Session(test_engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.id == original["session_id"]))
        assert row.generation == 0 and row.revoked_at is None
    assert client.get("/api/v1/auth/me", headers=headers(original)).status_code == 200
    monkeypatch.setattr(redis, "set", original_set)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}).status_code == 200


def test_commit_failure_after_cache_write_does_not_deliver_orphan(client, session_env, test_engine, monkeypatch):
    sessions, _, _, redis = session_env
    original = login(client)
    real_commit = Session.commit

    def fail_commit(db):
        raise RuntimeError("simulated commit outage")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated commit outage"):
        client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    monkeypatch.setattr(Session, "commit", real_commit)
    with Session(test_engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.id == original["session_id"]))
        assert row.generation == 0 and row.revoked_at is None
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert response.status_code == 200
    repeated = client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert repeated.json() == response.json()


def test_login_holds_verified_user_lock_until_issuance_then_reset_revokes(client, test_engine, session_env, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from app.api.v1 import auth as routes

    sessions, *_ = session_env
    issue = routes.issue_session

    def verify_lock_and_issue(db, user):
        # This would succeed (and reset could win) if /token committed between
        # password verification and issuance. Check using a real second connection.
        with Session(test_engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError) as error:
                other.scalar(select(User).where(User.id == user.id).with_for_update())
            assert error.value.orig.sqlstate == "55P03"
            other.rollback()
        return issue(db, user)

    monkeypatch.setattr(routes, "issue_session", verify_lock_and_issue)
    pair = login(client)
    with Session(test_engine) as reset:
        user = reset.scalar(select(User).where(User.username == "admin").with_for_update())
        user.password_hash = "reset-invalidates-previous-password"
        reset.flush()
        sessions.revoke_all_sessions(reset, user.id)
        reset.commit()
    assert client.get("/api/v1/auth/me", headers=headers(pair)).status_code == 401


def test_logout_with_refresh_revokes_when_access_expired_and_redis_down(client, test_engine, session_env, monkeypatch):
    from redis import Redis

    sessions, clock, *_ = session_env
    pair = login(client)
    clock[0] += timedelta(seconds=301)
    assert client.get("/api/v1/auth/me", headers=headers(pair)).status_code == 401
    monkeypatch.setattr(sessions, "_redis", Redis(host="127.0.0.1", port=1, socket_connect_timeout=.1, socket_timeout=.1))
    response = client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 204
    with Session(test_engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.id == pair["session_id"]))
        assert row.revoked_at == clock[0]
        assert row.generation == 0  # No rotation or cache is needed to revoke.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}).status_code == 204


def test_logout_with_signed_older_refresh_revokes_without_redis(client, test_engine, session_env, monkeypatch):
    from redis import Redis

    sessions, clock, *_ = session_env
    original = login(client)
    pair = original
    for _ in range(3):
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert response.status_code == 200
        pair = response.json()
    monkeypatch.setattr(sessions, "_redis", Redis(host="127.0.0.1", port=1, socket_connect_timeout=.1, socket_timeout=.1))
    assert client.post("/api/v1/auth/logout", json={"refresh_token": original["refresh_token"]}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers(pair)).status_code == 401


def test_logout_forged_or_wrong_kind_proof_does_not_revoke(client, session_env):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    original = login(client)
    claims = jwt.decode(original["refresh_token"], options={"verify_signature": False})
    forged = jwt.encode(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256")
    for proof in (str(original["session_id"]) + ".random", forged, original["access_token"]):
        assert client.post("/api/v1/auth/logout", json={"refresh_token": proof}).status_code == 401
        assert client.get("/api/v1/auth/me", headers=headers(original)).status_code == 200


def test_logout_uncommitted_refresh_cannot_revoke(client, test_engine, session_env):
    sessions, *_ = session_env
    original = login(client)
    with Session(test_engine) as db:
        orphan = sessions.rotate_session(db, original["refresh_token"])
        db.rollback()
    assert client.post("/api/v1/auth/logout", json={"refresh_token": orphan.refresh_token}).status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers(original)).status_code == 200
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]})
    assert response.status_code == 200
    assert client.post("/api/v1/auth/logout", json={"refresh_token": orphan.refresh_token}).status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers(response.json())).status_code == 200
