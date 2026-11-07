from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import jwt
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.models import AuthSession, ExternalIdentity, User
from app.services import auth
from test_accounts import PASSWORD, accounts
from test_api_security import AUDIENCE, GROUP, ISSUER, _token, jwks_server, rsa_key
from test_auth_sessions_api import client
from test_sessions import session_env


@pytest.fixture
def provider(monkeypatch, jwks_server):
    monkeypatch.setattr(settings, "authentik_enabled", True, raising=False)
    monkeypatch.setattr(settings, "authentik_issuer", ISSUER)
    monkeypatch.setattr(settings, "authentik_audience", AUDIENCE)
    monkeypatch.setattr(settings, "authentik_jwks_url", jwks_server)
    monkeypatch.setattr(settings, "authentik_admin_group", GROUP)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "_jwks_url", None)


def exchange(db, token):
    from app.services.oidc import exchange_authentik
    return exchange_authentik(db, token)


def changed_token(key, **changes):
    claims = jwt.decode(_token(key), options={"verify_signature": False})
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def test_disabled_provider_needs_no_oidc_env_and_never_fetches(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for key in ("ENABLED", "ISSUER", "AUDIENCE", "JWKS_URL", "ADMIN_GROUP"):
        monkeypatch.delenv(f"AUTHENTIK_{key}", raising=False)
    config = Settings()
    config.validate()
    assert config.authentik_enabled is False
    monkeypatch.setenv("AUTHENTIK_ISSUER", "not a URL" + "x" * 2048)
    Settings().validate()
    # Legacy settings cannot silently enable the provider.
    monkeypatch.setattr(settings, "authentik_enabled", False, raising=False)
    monkeypatch.setattr(settings, "authentik_issuer", ISSUER)
    monkeypatch.setattr(settings, "authentik_audience", AUDIENCE)
    monkeypatch.setattr(settings, "authentik_jwks_url", "http://127.0.0.1:1/jwks/")
    monkeypatch.setattr(settings, "authentik_admin_group", GROUP)
    def unexpected_fetch():
        pytest.fail("Disabled provider attempted JWKS access")
    monkeypatch.setattr(auth, "_client", unexpected_fetch)
    assert auth.configured() is False
    with pytest.raises(auth.AuthError) as caught:
        auth.verify_authentik_token("unused")
    assert caught.value.status_code == 503


@pytest.mark.parametrize("missing", ["ISSUER", "AUDIENCE", "ADMIN_GROUP"])
@pytest.mark.parametrize("environment", ["production", "test"])
def test_enabled_provider_requires_complete_config(monkeypatch, missing, environment):
    monkeypatch.setenv("APP_ENV", environment)
    for key, value in {"ENABLED": "true", "ISSUER": ISSUER, "AUDIENCE": AUDIENCE,
                       "JWKS_URL": "http://127.0.0.1/jwks/", "ADMIN_GROUP": GROUP}.items():
        monkeypatch.setenv(f"AUTHENTIK_{key}", value)
    Settings().validate()
    monkeypatch.delenv(f"AUTHENTIK_{missing}")
    with pytest.raises(RuntimeError, match="AUTHENTIK"):
        Settings().validate()


@pytest.mark.parametrize("flag", ["", "treu", "enabled", "1", "0", "yes", "no"])
def test_provider_flag_is_strict(monkeypatch, flag):
    monkeypatch.setenv("AUTHENTIK_ENABLED", flag)
    with pytest.raises(RuntimeError, match="AUTHENTIK_ENABLED"):
        Settings().validate()


@pytest.mark.parametrize("flag,expected", [("true", True), ("FALSE", False), (" True ", True)])
def test_provider_flag_accepts_explicit_booleans(monkeypatch, flag, expected):
    monkeypatch.setenv("AUTHENTIK_ENABLED", flag)
    assert Settings().authentik_enabled is expected


def test_enabled_provider_rejects_unstorable_issuer(monkeypatch):
    monkeypatch.setenv("AUTHENTIK_ENABLED", "true")
    monkeypatch.setenv("AUTHENTIK_ISSUER", "https://auth.test/" + "x" * 2048)
    monkeypatch.setenv("AUTHENTIK_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("AUTHENTIK_ADMIN_GROUP", GROUP)
    with pytest.raises(RuntimeError, match="AUTHENTIK_ISSUER"):
        Settings().validate()


def test_external_identity_does_not_link_by_email(client, provider, rsa_key, test_engine):
    response = client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    pair = response.json()
    with Session(test_engine) as db:
        local = db.scalar(select(User).where(User.username == "admin"))
        external = db.get(User, pair["user"]["id"])
        identity = db.scalar(select(ExternalIdentity))
        assert external.id != local.id
        assert external.password_hash is None
        assert identity.user_id == external.id
        assert (identity.issuer, identity.subject) == (ISSUER, "user-123")
        assert db.scalar(select(func.count()).select_from(User)) == 2
    assert pair["user"]["email"] is None and pair["user"]["groups"] == []
    claims = jwt.decode(pair["access_token"], options={"verify_signature": False})
    assert claims["iss"] == "tdl-console" and claims["aud"] == "tdl-api"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}).status_code == 200
    repeated = client.post("/api/v1/auth/exchange", json={"access_token": changed_token(rsa_key, email="new@example.com", preferred_username="new-name")})
    assert repeated.status_code == 200
    assert repeated.json()["user"]["id"] == pair["user"]["id"]


@pytest.mark.parametrize("groups", [[], GROUP, {GROUP: True}, [GROUP + "-other"], [GROUP, 1], None])
def test_group_or_disabled_identity_denied(client, provider, rsa_key, test_engine, groups):
    response = client.post("/api/v1/auth/exchange", json={"access_token": changed_token(rsa_key, groups=groups)})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_disabled_external_user_is_not_recreated(client, provider, rsa_key, test_engine):
    original = client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)})
    assert original.status_code == 200, original.text
    with Session(test_engine) as db:
        user = db.get(User, original.json()["user"]["id"])
        user.active = False
        db.commit()
    denied = client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)})
    assert denied.status_code == 403
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1


@pytest.mark.parametrize("enabled", [True, False])
def test_local_login_survives_oidc_outage(client, provider, monkeypatch, enabled):
    monkeypatch.setattr(settings, "authentik_enabled", enabled, raising=False)
    monkeypatch.setattr(settings, "authentik_jwks_url", "http://127.0.0.1:1/unavailable")
    if not enabled:
        for name in ("issuer", "audience", "admin_group"):
            monkeypatch.setattr(settings, f"authentik_{name}", "")
    response = client.post("/api/v1/auth/token", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}).status_code == 200


@pytest.mark.parametrize("extra", [{"user_id": "chosen"}, {"groups": [GROUP]}, {"issuer": ISSUER}])
def test_exchange_only_accepts_token(client, provider, rsa_key, extra):
    token = _token(rsa_key)
    response = client.post("/api/v1/auth/exchange", json={"access_token": token, **extra})
    assert response.status_code == 422
    assert token not in response.text


def test_first_login_race_has_one_identity_and_no_orphan_users(provider, rsa_key, test_engine, session_env):
    barrier = Barrier(2)
    def inserting(mapper, connection, target):
        # Both connections saw no identity and are creating a user. One MUST
        # lose the unique identity key; its savepoint must remove the user too.
        barrier.wait(timeout=10)
    token = _token(rsa_key)
    def login():
        with Session(test_engine) as db:
            pair = exchange(db, token)
            db.commit()
            return pair.user.id
    event.listen(User, "before_insert", inserting)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(login) for _ in range(2)]
            ids = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(User, "before_insert", inserting)
    assert ids[0] == ids[1]
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 2


def test_exchange_is_atomic_and_holds_user_lock(provider, rsa_key, test_engine, session_env, monkeypatch):
    import app.services.oidc as oidc
    original_issue = oidc.issue_session
    def locked_issue(db, user):
        with Session(test_engine) as other:
            # New users are invisible; existing users must remain locked.
            if other.get(User, user.id) is not None:
                other.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(OperationalError) as error:
                    other.scalar(select(User).where(User.id == user.id).with_for_update())
                assert error.value.orig.sqlstate == "55P03"
        return original_issue(db, user)
    monkeypatch.setattr(oidc, "issue_session", locked_issue)
    with Session(test_engine) as db:
        first = exchange(db, _token(rsa_key))
        with Session(test_engine) as other:
            assert other.get(User, first.user.id) is None
        db.commit()
        exchange(db, _token(rsa_key))
        db.rollback()
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1


def test_failed_exchange_commit_rolls_back_provisioning(client, provider, rsa_key, test_engine, monkeypatch):
    def fail_commit(db):
        raise RuntimeError("simulated commit outage")
    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated commit outage"):
        client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)})
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


@pytest.mark.parametrize("subject", ["", "x" * 256, "bad\x00subject", None, 123])
def test_invalid_subject_is_rejected_before_database_write(client, provider, rsa_key, subject):
    response = client.post("/api/v1/auth/exchange", json={"access_token": changed_token(rsa_key, sub=subject)})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_unstorable_display_name_does_not_break_login(client, provider, rsa_key):
    response = client.post("/api/v1/auth/exchange", json={"access_token": changed_token(rsa_key, name="bad\x00name")})
    assert response.status_code == 200, response.text
    assert response.json()["user"]["name"] is None


@pytest.mark.parametrize("mutation,code", [("algorithm", "invalid_token"), ("signature", "invalid_token"),
    ("issuer", "invalid_issuer"), ("audience", "invalid_audience"), ("expired", "token_expired")])
def test_exchange_rejects_invalid_external_crypto(client, provider, rsa_key, session_env, mutation, code):
    claims = jwt.decode(_token(rsa_key), options={"verify_signature": False})
    if mutation == "issuer": claims["iss"] += "/"
    if mutation == "audience": claims["aud"] = "tdl-api"
    if mutation == "expired": claims["exp"] = claims["iat"] - 1
    if mutation == "algorithm":
        token = jwt.encode(claims, "an-untrusted-secret" * 4, algorithm="HS256", headers={"kid": "test-key"})
    else:
        key = session_env[2] if mutation == "signature" else rsa_key
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
    response = client.post("/api/v1/auth/exchange", json={"access_token": token})
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == code
    assert token not in response.text


def test_issuer_and_subject_are_the_only_identity_key(client, provider, rsa_key, monkeypatch):
    first = client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)})
    second = client.post("/api/v1/auth/exchange", json={"access_token": changed_token(rsa_key, sub="different-subject")})
    monkeypatch.setattr(settings, "authentik_issuer", ISSUER + "/other")
    third = client.post("/api/v1/auth/exchange", json={"access_token": changed_token(rsa_key, iss=ISSUER + "/other")})
    assert first.status_code == second.status_code == third.status_code == 200
    assert len({item.json()["user"]["id"] for item in (first, second, third)}) == 3


def test_provider_and_group_changes_do_not_silently_revoke_native_sessions(client, provider, rsa_key, monkeypatch):
    original = client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)})
    assert original.status_code == 200
    pair = original.json()
    # Group membership is checked at sign-in; existing TDL sessions are native.
    assert client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key, groups=())}).status_code == 403
    monkeypatch.setattr(settings, "authentik_enabled", False)
    assert client.post("/api/v1/auth/exchange", json={"access_token": _token(rsa_key)}).status_code == 503
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}).status_code == 200
    assert client.post("/api/v1/auth/revoke-all", headers={"Authorization": f"Bearer {pair['access_token']}"}).status_code == 204
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}).status_code == 401


def test_exchange_preserves_csrf_and_secret_repr(client, provider, rsa_key):
    from app.schemas import ExchangeRequest
    token = _token(rsa_key)
    assert token not in repr(ExchangeRequest(access_token=token))
    client.headers.pop("X-Requested-With")
    assert client.post("/api/v1/auth/exchange", json={"access_token": token}).status_code == 403
    client.headers["X-Requested-With"] = "tdl-web"
    assert client.post("/api/v1/auth/exchange", json={"access_token": token}, headers={"Origin": "https://evil.example"}).status_code == 403
