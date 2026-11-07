import hashlib
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from redis import Redis
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthSession, User
from app.services.auth import AuthError


@pytest.fixture
def session_env(monkeypatch, tmp_path):
    import importlib.util

    assert importlib.util.find_spec("app.services.sessions"), "Native session service is required"
    from app.services import sessions

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setattr(settings, "jwt_private_key_file", private)
    monkeypatch.setattr(settings, "jwt_public_key_file", public)
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], socket_timeout=1, socket_connect_timeout=1)
    prefix = f"tdl:test:sessions:{uuid4().hex}"
    monkeypatch.setattr(settings, "auth_rotation_prefix", prefix)
    monkeypatch.setattr(sessions, "_redis", redis)
    clock = [datetime.now(UTC).replace(microsecond=0)]
    monkeypatch.setattr(sessions, "_now", lambda: clock[0])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    yield sessions, clock, key, redis
    keys = list(redis.scan_iter(f"{prefix}:*"))
    if keys:
        redis.delete(*keys)
    redis.close()


@pytest.fixture
def issued(db_session, session_env):
    sessions, clock, key, redis = session_env
    user = User(username="admin", display_name="Administrator", must_change_password=True)
    db_session.add(user)
    db_session.flush()
    pair = sessions.issue_session(db_session, user)
    db_session.commit()
    return user, pair


def test_issue_signed_safe_identity_and_hash_only(db_session, session_env, issued, test_engine):
    sessions, clock, key, redis = session_env
    user, pair = issued
    payload = jwt.decode(pair.access_token, key.public_key(), algorithms=["RS256"], issuer="tdl-console", audience="tdl-api")
    assert payload["sub"] == str(user.id)
    assert payload["sid"] == str(pair.session_id)
    assert payload["exp"] - payload["iat"] == 300
    assert pair.expires_at == payload["exp"]
    assert pair.must_change_password and pair.user.username == "admin"
    assert "password" not in pair.user.model_dump_json().replace("must_change_password", "")
    with Session(test_engine) as db:
        row = db.get(AuthSession, pair.session_id)
        assert row.refresh_token_hash == hashlib.sha256(pair.refresh_token.encode()).hexdigest()
        assert row.absolute_expires_at == clock[0] + timedelta(seconds=28800)
        assert row.idle_expires_at == clock[0] + timedelta(seconds=1800)
    assert sessions.verify_session(db_session, pair.access_token).id == user.id


@pytest.mark.parametrize("mutation", ["hs256", "issuer", "audience", "expired", "sub", "sid", "malformed_sid", "missing_iat", "refresh_as_access"])
def test_invalid_jwt_rejected(db_session, session_env, issued, mutation):
    sessions, clock, key, redis = session_env
    user, pair = issued
    claims = jwt.decode(pair.access_token, options={"verify_signature": False})
    if mutation == "refresh_as_access":
        token = pair.refresh_token
    else:
        if mutation == "issuer": claims["iss"] = "other"
        if mutation == "audience": claims["aud"] = "other"
        if mutation == "expired": claims["exp"] = int(clock[0].timestamp())
        if mutation in {"sid", "sub"}: claims[mutation] = str(uuid4())
        if mutation == "malformed_sid": claims["sid"] = 123
        if mutation == "missing_iat": claims.pop("iat")
        token = jwt.encode(claims, "a-long-secret" * 4 if mutation == "hs256" else key, algorithm="HS256" if mutation == "hs256" else "RS256")
    with pytest.raises(AuthError) as error:
        sessions.verify_session(db_session, token)
    assert error.value.status_code == 401


@pytest.mark.parametrize("disabled", [False, True])
def test_revoked_or_disabled_blocks_live_access(db_session, session_env, issued, disabled):
    sessions, *_ = session_env
    user, pair = issued
    if disabled:
        user.active = False
        db_session.flush()
    else:
        sessions.revoke_session(db_session, pair.session_id)
    db_session.commit()
    with pytest.raises(AuthError):
        sessions.verify_session(db_session, pair.access_token)


def test_polling_and_refresh_do_not_extend_idle_or_absolute(db_session, session_env, issued):
    sessions, clock, *_ = session_env
    user, pair = issued
    start = clock[0]
    for delta in (299, 500, 750, 1000, 1250, 1500, 1799):
        clock[0] = start + timedelta(seconds=delta)
        pair = sessions.rotate_session(db_session, pair.refresh_token)
        db_session.commit()
        sessions.verify_session(db_session, pair.access_token)
    row = db_session.get(AuthSession, pair.session_id)
    assert row.last_activity_at == start
    assert row.absolute_expires_at == start + timedelta(seconds=28800)
    assert row.idle_expires_at == start + timedelta(seconds=1800)
    clock[0] = start + timedelta(seconds=1800)
    with pytest.raises(AuthError): sessions.verify_session(db_session, pair.access_token)
    with pytest.raises(AuthError): sessions.rotate_session(db_session, pair.refresh_token)


def test_activity_throttled_and_absolute_limit(db_session, session_env, issued):
    sessions, clock, *_ = session_env
    user, pair = issued
    start = clock[0]
    clock[0] += timedelta(seconds=59)
    sessions.record_activity(db_session, pair.session_id)
    assert db_session.get(AuthSession, pair.session_id).last_activity_at == start
    clock[0] += timedelta(seconds=1)
    sessions.record_activity(db_session, pair.session_id)
    db_session.commit()
    assert db_session.get(AuthSession, pair.session_id).idle_expires_at == clock[0] + timedelta(seconds=1800)
    for delta in range(1200, 28800, 1200):
        clock[0] = start + timedelta(seconds=delta)
        sessions.record_activity(db_session, pair.session_id)
        pair = sessions.rotate_session(db_session, pair.refresh_token)
        db_session.commit()
    clock[0] = start + timedelta(seconds=28799)
    sessions.record_activity(db_session, pair.session_id)
    pair = sessions.rotate_session(db_session, pair.refresh_token)
    db_session.commit()
    assert pair.expires_at == int((start + timedelta(seconds=28800)).timestamp())
    clock[0] += timedelta(seconds=1)
    with pytest.raises(AuthError): sessions.rotate_session(db_session, pair.refresh_token)


def test_refresh_concurrent_across_connections(test_engine, session_env, issued):
    sessions, *_ = session_env
    _, original = issued
    barrier = Barrier(2)

    def rotate():
        with Session(test_engine) as db:
            barrier.wait(timeout=10)
            result = sessions.rotate_session(db, original.refresh_token)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    assert results[0] == results[1]
    assert results[0].refresh_token != original.refresh_token
    with Session(test_engine) as db:
        assert db.get(AuthSession, original.session_id).generation == 1
        assert sessions.verify_session(db, results[0].access_token).username == "admin"


@pytest.mark.parametrize("generations", [1, 3])
def test_reused_refresh_revokes_family(db_session, session_env, issued, generations):
    sessions, clock, *_ = session_env
    _, original = issued
    pair = original
    for _ in range(generations):
        pair = sessions.rotate_session(db_session, pair.refresh_token)
        db_session.commit()
    clock[0] += timedelta(seconds=6)
    with pytest.raises(sessions.RefreshReplay):
        sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()  # Explicit caller contract: persist replay revocation before 401.
    with pytest.raises(AuthError): sessions.verify_session(db_session, pair.access_token)


def test_random_token_cannot_revoke_known_session(db_session, session_env, issued):
    sessions, clock, key, _ = session_env
    _, pair = issued
    claims = jwt.decode(pair.refresh_token, options={"verify_signature": False})
    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (str(pair.session_id) + ".random", jwt.encode(claims, forged_key, algorithm="RS256"), pair.access_token):
        with pytest.raises(AuthError): sessions.rotate_session(db_session, token)
        db_session.rollback()
        assert sessions.verify_session(db_session, pair.access_token).username == "admin"


def test_rollback_cache_cannot_authorize_orphan_successor(db_session, session_env, issued):
    sessions, clock, key, redis = session_env
    _, original = issued
    orphan = sessions.rotate_session(db_session, original.refresh_token)
    db_session.rollback()
    with pytest.raises(AuthError): sessions.rotate_session(db_session, orphan.refresh_token)
    db_session.rollback()
    actual = sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()
    assert actual.refresh_token != orphan.refresh_token
    assert sessions.rotate_session(db_session, original.refresh_token) == actual
    db_session.commit()
    keys = list(redis.scan_iter(f"{settings.auth_rotation_prefix}:*"))
    assert keys
    assert all(0 < redis.ttl(k) <= 5 for k in keys)
    for k in keys:
        encrypted = redis.get(k)
        assert actual.refresh_token.encode() not in encrypted
        assert actual.access_token.encode() not in encrypted


def test_redis_failure_rolls_back_without_revocation(db_session, session_env, issued, monkeypatch):
    sessions, clock, key, redis = session_env
    _, original = issued
    monkeypatch.setattr(sessions, "_redis", Redis(host="127.0.0.1", port=1, socket_connect_timeout=.1, socket_timeout=.1))
    with pytest.raises(AuthError) as error:
        sessions.rotate_session(db_session, original.refresh_token)
    assert error.value.status_code == 503
    db_session.rollback()
    assert sessions.verify_session(db_session, original.access_token).username == "admin"
    assert db_session.get(AuthSession, original.session_id).generation == 0


def test_revoke_all_and_helpers_do_not_commit(db_session, session_env, issued, test_engine):
    sessions, *_ = session_env
    user, original = issued
    second = sessions.issue_session(db_session, user)
    db_session.rollback()
    with Session(test_engine) as other:
        assert other.get(AuthSession, second.session_id) is None
    second = sessions.issue_session(db_session, user)
    db_session.commit()
    sessions.revoke_all_sessions(db_session, user.id)
    db_session.commit()
    for pair in (original, second):
        with pytest.raises(AuthError): sessions.verify_session(db_session, pair.access_token)


@pytest.mark.parametrize("generations", [1, 3])
def test_lost_cache_during_grace_is_transient_even_for_older_generation(db_session, session_env, issued, generations):
    sessions, clock, key, redis = session_env
    _, original = issued
    pair = original
    for _ in range(generations):
        pair = sessions.rotate_session(db_session, pair.refresh_token)
        db_session.commit()
    keys = list(redis.scan_iter(f"{settings.auth_rotation_prefix}:*"))
    redis.delete(*keys)
    clock[0] += timedelta(seconds=4)
    with pytest.raises(AuthError) as error:
        sessions.rotate_session(db_session, original.refresh_token)
    assert error.value.status_code == 503
    db_session.rollback()
    assert sessions.verify_session(db_session, pair.access_token).username == "admin"
    clock[0] += timedelta(seconds=1)
    with pytest.raises(sessions.RefreshReplay):
        sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()
    with pytest.raises(AuthError): sessions.verify_session(db_session, pair.access_token)


def test_advanced_cache_successor_is_conflict_without_revoke(db_session, session_env, issued):
    sessions, clock, *_ = session_env
    _, original = issued
    second = sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()
    third = sessions.rotate_session(db_session, second.refresh_token)
    db_session.commit()
    with pytest.raises(AuthError) as error:
        sessions.rotate_session(db_session, original.refresh_token)
    assert error.value.status_code == 409
    db_session.rollback()
    assert sessions.verify_session(db_session, third.access_token).username == "admin"


def test_cache_hit_never_renews_its_window_or_expirations(db_session, session_env, issued):
    sessions, clock, key, redis = session_env
    _, original = issued
    successor = sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()
    for _ in range(4):
        clock[0] += timedelta(seconds=1)
        assert sessions.rotate_session(db_session, original.refresh_token) == successor
        db_session.commit()
    clock[0] += timedelta(seconds=1)
    with pytest.raises(sessions.RefreshReplay):
        sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()


def test_corrupt_encrypted_cache_fails_closed_without_revocation(db_session, session_env, issued):
    sessions, clock, key, redis = session_env
    _, original = issued
    successor = sessions.rotate_session(db_session, original.refresh_token)
    db_session.commit()
    keys = list(redis.scan_iter(f"{settings.auth_rotation_prefix}:*"))
    redis.set(keys[0], b"tampered", ex=5)
    with pytest.raises(AuthError) as error:
        sessions.rotate_session(db_session, original.refresh_token)
    assert error.value.status_code == 503
    db_session.rollback()
    assert sessions.verify_session(db_session, successor.access_token).username == "admin"


def _process_rotate(url, schema, private, public, prefix, token, barrier):
    # Spawn starts a fresh interpreter: no inherited engine, Redis client, key
    # objects, cache, mutex, or monkeypatch from the parent process.
    from pathlib import Path
    from app.services import sessions

    settings.jwt_private_key_file = Path(private)
    settings.jwt_public_key_file = Path(public)
    settings.auth_rotation_prefix = prefix
    sessions._redis = Redis.from_url(os.environ["TEST_REDIS_URL"], socket_timeout=1, socket_connect_timeout=1)
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with Session(engine) as db:
            barrier.wait(timeout=20)
            result = sessions.rotate_session(db, token)
            db.commit()
            return result.model_dump(mode="json")
    finally:
        engine.dispose()
        sessions._redis.close()


def test_refresh_concurrent_across_processes(test_engine, db_session, session_env, issued):
    _, original = issued
    schema = db_session.scalar(text("SELECT current_schema()"))
    db_session.rollback()
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager, ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        barrier = manager.Barrier(2)
        args = (test_engine.url.render_as_string(hide_password=False), schema, str(settings.jwt_private_key_file),
                str(settings.jwt_public_key_file), settings.auth_rotation_prefix, original.refresh_token, barrier)
        jobs = [pool.submit(_process_rotate, *args) for _ in range(2)]
        results = [job.result(timeout=30) for job in jobs]
    assert results[0] == results[1]
    assert results[0]["refresh_token"] != original.refresh_token
    assert db_session.get(AuthSession, original.session_id).generation == 1


def test_uncommitted_rotation_not_visible_until_transaction_finishes(test_engine, db_session, session_env, issued):
    sessions, *_ = session_env
    _, original = issued
    orphan = sessions.rotate_session(db_session, original.refresh_token)
    # A second connection times out at the user lock even though Redis already
    # contains the successor: it cannot consume an uncommitted cache response.
    from sqlalchemy.exc import OperationalError
    with Session(test_engine) as other:
        other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError) as error:
            sessions.rotate_session(other, original.refresh_token)
        assert error.value.orig.sqlstate == "55P03"
        other.rollback()
    db_session.rollback()
    with Session(test_engine) as other:
        actual = sessions.rotate_session(other, original.refresh_token)
        other.commit()
    assert actual.refresh_token != orphan.refresh_token


def test_stale_identity_map_cannot_bypass_revocation(test_engine, db_session, session_env, issued):
    sessions, *_ = session_env
    user, pair = issued
    assert sessions.verify_session(db_session, pair.access_token).username == "admin"
    with Session(test_engine) as other:
        sessions.revoke_session(other, pair.session_id)
        other.commit()
    with pytest.raises(AuthError): sessions.verify_session(db_session, pair.access_token)


def test_missing_key_fails_safely_without_session(db_session, session_env, issued, monkeypatch, tmp_path):
    sessions, *_ = session_env
    user, pair = issued
    monkeypatch.setattr(settings, "jwt_private_key_file", tmp_path / "not-present.pem")
    with pytest.raises(AuthError) as error:
        sessions.issue_session(db_session, user)
    assert error.value.status_code == 503
    assert "not-present" not in str(error.value)
    db_session.rollback()
    assert len(db_session.scalars(select(AuthSession)).all()) == 1
