import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

PASSWORD = "  correct horse battery  "


@pytest.fixture
def accounts(monkeypatch):
    from app.config import settings
    from app.services import accounts

    client = Redis.from_url(os.environ["TEST_REDIS_URL"], socket_connect_timeout=1, socket_timeout=1)
    prefix = f"tdl:test:accounts:{uuid4().hex}"
    monkeypatch.setattr(settings, "auth_rate_limit_prefix", prefix)
    monkeypatch.setattr(accounts, "_redis", client)
    yield accounts
    keys = list(client.scan_iter(f"{prefix}:*"))
    if keys:
        client.delete(*keys)
    client.close()


def test_password_is_hashed_and_username_canonical(db_session, test_engine, accounts):
    from app.schemas import LocalUserRead

    user = accounts.create_local_user(db_session, "Alice.Admin", PASSWORD, must_change_password=True)
    assert user.username == "alice.admin"
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert isinstance(user.id, UUID)
    assert user.must_change_password and user.active
    assert user.created_at.utcoffset() == timedelta(0)
    public = LocalUserRead.model_validate(user).model_dump_json()
    for representation in (repr(user), public):
        assert PASSWORD not in representation
        assert user.password_hash not in representation
    with Session(test_engine) as other:
        assert other.get(type(user), user.id) is None
    assert accounts.verify_credentials(db_session, "ALICE.ADMIN", PASSWORD, origin="server-peer") is user
    db_session.rollback()
    with Session(test_engine) as other:
        assert other.get(type(user), user.id) is None


def test_unknown_and_wrong_password_are_generic(db_session, accounts):
    accounts.create_local_user(db_session, "alice", PASSWORD)
    errors = []
    for username, password in [("unknown", PASSWORD), ("alice", "wrong password"), ("аlice", PASSWORD)]:
        with pytest.raises(accounts.AuthError) as caught:
            accounts.verify_credentials(db_session, username, password, origin="peer")
        errors.append((caught.value.status_code, caught.value.code, str(caught.value)))
    assert errors[0] == errors[1] == errors[2]
    assert errors[0][0] == 401


def test_duplicate_username_rejected(db_session, accounts):
    accounts.create_local_user(db_session, "alice", PASSWORD)
    with pytest.raises(accounts.AuthError) as caught:
        accounts.create_local_user(db_session, "ALICE", PASSWORD)
    assert caught.value.status_code == 409
    assert PASSWORD not in str(caught.value)
    assert db_session.scalar(text("SELECT count(*) FROM users")) == 1


def test_disabled_user_rejected(db_session, accounts):
    user = accounts.create_local_user(db_session, "alice", PASSWORD)
    user.active = False
    db_session.flush()
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "alice", PASSWORD, origin="peer")
    assert caught.value.status_code == 401


def test_rate_limit_and_redis_failure(db_session, accounts, monkeypatch):
    accounts.create_local_user(db_session, "alice", PASSWORD)
    for _ in range(5):
        with pytest.raises(accounts.AuthError) as caught:
            accounts.verify_credentials(db_session, "ALICE", "wrong password", origin="peer")
        assert caught.value.status_code == 401
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "alice", PASSWORD, origin="another-peer")
    assert caught.value.status_code == 429
    monkeypatch.setattr(accounts, "_redis", Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1))
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "someone", PASSWORD, origin="peer")
    assert caught.value.status_code == 503
    assert "redis" not in str(caught.value).lower()


def test_origin_limit_and_expiration(db_session, accounts):
    for i in range(30):
        with pytest.raises(accounts.AuthError) as caught:
            accounts.verify_credentials(db_session, f"missing{i}", PASSWORD, origin="peer")
        assert caught.value.status_code == 401
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "different", PASSWORD, origin="peer")
    assert caught.value.status_code == 429
    keys = list(accounts._redis.scan_iter(f"{accounts.settings.auth_rate_limit_prefix}:*"))
    assert keys and all(0 < accounts._redis.ttl(key) <= 900 for key in keys)
    for key in keys:
        accounts._redis.pexpire(key, 1)
    # Redis expiration is checked synchronously, without a 15 minute test wait.
    import time
    time.sleep(0.01)
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "different", PASSWORD, origin="peer")
    assert caught.value.status_code == 401


def test_successes_do_not_consume_failure_allowance(db_session, accounts):
    accounts.create_local_user(db_session, "alice", PASSWORD)
    for _ in range(6):
        accounts.verify_credentials(db_session, "alice", PASSWORD, origin="peer")


def test_success_does_not_start_failure_window(db_session, accounts):
    accounts.create_local_user(db_session, "alice", PASSWORD)
    accounts.verify_credentials(db_session, "alice", PASSWORD, origin="peer")
    assert list(accounts._redis.scan_iter(f"{accounts.settings.auth_rate_limit_prefix}:*")) == []


@pytest.mark.parametrize("username", ["ab", "a" * 65, "álíce", "Ａlice", "alice\u200b", "alice ", "alice\n"])
def test_invalid_username_rejected_without_unicode_folding(db_session, accounts, username):
    with pytest.raises(ValueError):
        accounts.create_local_user(db_session, username, PASSWORD)
    assert db_session.scalar(text("SELECT count(*) FROM users")) == 0


@pytest.mark.parametrize("password", ["short", "a" * 129])
def test_invalid_password_rejected_before_hash(db_session, accounts, monkeypatch, password):
    def forbidden(*args):
        pytest.fail("Invalid password must never reach Argon2")
    monkeypatch.setattr(accounts, "_hash_password", forbidden)
    monkeypatch.setattr(type(accounts._hasher), "verify", forbidden)
    with pytest.raises(ValueError):
        accounts.create_local_user(db_session, "alice", password)
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "alice", password, origin="peer")
    assert caught.value.status_code == 401


def test_verification_holds_user_lock_until_caller_finishes(db_session, test_engine, accounts):
    user = accounts.create_local_user(db_session, "alice", PASSWORD)
    db_session.commit()
    # A stale identity map must not bypass a reset committed by another caller.
    with Session(test_engine) as other:
        other.execute(text("UPDATE users SET active = false WHERE id = :id"), {"id": user.id})
        other.commit()
    with pytest.raises(accounts.AuthError):
        accounts.verify_credentials(db_session, "alice", PASSWORD, origin="peer")
    db_session.rollback()
    user.active = True
    db_session.commit()
    accounts.verify_credentials(db_session, "alice", PASSWORD, origin="peer")
    with Session(test_engine) as other:
        other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            other.execute(text("UPDATE users SET active = false WHERE id = :id"), {"id": user.id})
        other.rollback()
    db_session.rollback()
    with Session(test_engine) as other:
        other.execute(text("UPDATE users SET active = false WHERE id = :id"), {"id": user.id})
        other.commit()


def test_identity_schema_constraints_and_utc(db_session, accounts):
    from app.models import AuditEvent, AuthSession, ExternalIdentity, User
    user = accounts.create_local_user(db_session, "alice", PASSWORD)
    now = datetime.now(UTC)
    identity = ExternalIdentity(user_id=user.id, issuer="https://issuer/", subject="subject")
    session = AuthSession(user_id=user.id, refresh_token_hash="a" * 64, absolute_expires_at=now + timedelta(hours=8), idle_expires_at=now + timedelta(minutes=30))
    audit = AuditEvent(actor_id=user.id, action="user.create", target_id=str(user.id), outcome="success")
    db_session.add_all([identity, session, audit])
    db_session.commit()
    db_session.expire_all()
    for value in (user.created_at, identity.created_at, session.created_at, session.last_activity_at, audit.created_at):
        assert value.utcoffset() == timedelta(0)
    assert "a" * 64 not in repr(session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ExternalIdentity(user_id=user.id, issuer="https://issuer/", subject="subject"))
        db_session.flush()
    assert db_session.scalar(select(User).where(User.username == "alice")) is not None


def test_parallel_failures_cannot_bypass_account_limit(test_engine, accounts):
    def attempt(i):
        with Session(test_engine) as db:
            try:
                accounts.verify_credentials(db, "unknown", PASSWORD, origin=f"peer{i}")
            except accounts.AuthError as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(attempt, range(12)))
    assert statuses.count(401) == 5
    assert statuses.count(429) == 7


def test_external_account_without_password_cannot_login(db_session, accounts):
    from app.models import User
    db_session.add(User(username="external", password_hash=None))
    db_session.flush()
    with pytest.raises(accounts.AuthError) as caught:
        accounts.verify_credentials(db_session, "external", PASSWORD, origin="peer")
    assert caught.value.status_code == 401


@pytest.mark.parametrize("password", [" " * 12, "界" * 128])
def test_password_boundaries_are_not_trimmed_or_truncated(db_session, accounts, password):
    accounts.create_local_user(db_session, "alice", password)
    assert accounts.verify_credentials(db_session, "alice", password, origin="peer").username == "alice"
    with pytest.raises(accounts.AuthError):
        accounts.verify_credentials(db_session, "alice", password[:-1], origin="peer")
