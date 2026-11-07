from __future__ import annotations

import base64
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.main import app
from app.services import auth
from test_sessions import session_env

ISSUER = "https://auth.test/application/o/tdl-console"
AUDIENCE = "tdl-console"
GROUP = "tdl-admin"


def test_config_preserves_oidc_issuer_exactly(monkeypatch):
    issuer = "https://auth.test/application/o/tdl-console/"
    monkeypatch.setenv("AUTHENTIK_ISSUER", issuer)
    monkeypatch.delenv("AUTHENTIK_JWKS_URL", raising=False)
    config = Settings()
    assert config.authentik_issuer == issuer
    assert config.authentik_jwks_url == f"{issuer}jwks/"


@pytest.mark.parametrize("url", [None, "", "sqlite:///:memory:", "mysql://host/db", "not-a-url", "postgresql://host", "postgresql+psycopg2://host/db"])
def test_config_requires_postgresql(monkeypatch, url):
    if url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(RuntimeError, match="DATABASE_URL.*PostgreSQL"):
        Settings().validate()


@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+psycopg"])
def test_config_accepts_postgresql_and_preserves_production_oidc(monkeypatch, scheme):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://user:secret@host/tdl")
    monkeypatch.setenv("AUTHENTIK_ISSUER", ISSUER)
    monkeypatch.setenv("AUTHENTIK_AUDIENCE", AUDIENCE)
    config = Settings()
    config.validate()
    assert config.database_url == "postgresql+psycopg://user:secret@host/tdl"
    monkeypatch.delenv("AUTHENTIK_ISSUER")
    monkeypatch.delenv("AUTHENTIK_AUDIENCE")
    monkeypatch.delenv("AUTHENTIK_JWKS_URL", raising=False)
    with pytest.raises(RuntimeError, match="AUTHENTIK"):
        Settings().validate()


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks_server(rsa_key):
    public = rsa_key.public_key().public_numbers()
    payload = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key",
                "use": "sig",
                "alg": "RS256",
                "n": _b64(public.n),
                "e": _b64(public.e),
            }
        ]
    }
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Reproduce the reverse proxy rejecting Python's generic default User-Agent.
            if self.headers.get("User-Agent", "").startswith("Python-urllib/"):
                self.send_response(403)
                self.end_headers()
                return
            if self.path == "/jwks/":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/jwks/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def authentik_settings(monkeypatch, jwks_server):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "authentik_issuer", ISSUER)
    monkeypatch.setattr(settings, "authentik_audience", AUDIENCE)
    monkeypatch.setattr(settings, "authentik_jwks_url", jwks_server)
    monkeypatch.setattr(settings, "authentik_admin_group", GROUP)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "_jwks_url", None)


@pytest.fixture
def api_client(monkeypatch, test_engine):
    from app import database
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=test_engine, expire_on_commit=False))
    from app.services.status import status_service

    monkeypatch.setattr("app.main.init_db", lambda: None)
    monkeypatch.setattr(
        status_service,
        "get",
        lambda force=False: {
            "environment": "test",
            "version": "1.0.0",
            "session_active": False,
            "session_error": None,
            "tdl_installed": False,
            "tdl_binary": "tdl",
            "redis_connected": False,
            "redis_error": None,
            "worker_connected": False,
            "worker_count": 0,
            "storage": "/tmp/sessions",
            "can_start_services": True,
            "authentik_configured": True,
        },
    )
    with TestClient(app) as client:
        yield client


def _token(rsa_key, *, groups=(GROUP,), audience=AUDIENCE, issuer=ISSUER, expires_in=300):
    now = datetime.now(UTC)
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": "user-123",
        "preferred_username": "admin",
        "email": "admin@example.com",
        "name": "Admin",
        "groups": list(groups),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(
        claims,
        rsa_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def native_pair(db_session, session_env):
    from app.models import User
    sessions, *_ = session_env
    user = User(username="admin", display_name="Admin")
    db_session.add(user)
    db_session.flush()
    pair = sessions.issue_session(db_session, user)
    db_session.commit()
    return pair


def test_health_is_public(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_health_is_public(api_client):
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200


def test_security_headers_are_present(api_client):
    response = api_client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_status_requires_bearer(api_client):
    response = api_client.get("/api/v1/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_valid_authentik_token_is_not_accepted_by_api(api_client, rsa_key, session_env):
    response = api_client.get("/api/v1/status", headers=_auth(_token(rsa_key)))
    assert response.status_code == 401


def test_native_session_is_accepted(api_client, native_pair):
    response = api_client.get("/api/v1/status", headers=_auth(native_pair.access_token))
    assert response.status_code == 200
    assert response.json()["authentik_configured"] is True


@pytest.mark.parametrize("mutation,code", [("issuer", "invalid_issuer"), ("audience", "invalid_audience"), ("expired", "token_expired"), ("algorithm", "invalid_session")])
def test_native_api_rejects_invalid_jwt(api_client, native_pair, session_env, mutation, code):
    _, clock, key, _ = session_env
    claims = jwt.decode(native_pair.access_token, options={"verify_signature": False})
    if mutation == "issuer": claims["iss"] = "other"
    if mutation == "audience": claims["aud"] = "other"
    if mutation == "expired": claims["exp"] = int(clock[0].timestamp())
    token = jwt.encode(claims, "an-untrusted-key" * 4 if mutation == "algorithm" else key, algorithm="HS256" if mutation == "algorithm" else "RS256")
    response = api_client.get("/api/v1/status", headers=_auth(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code


def test_missing_oidc_group_is_forbidden(rsa_key):
    with pytest.raises(auth.AuthError) as error:
        auth.verify_authentik_token(_token(rsa_key, groups=()))
    assert error.value.status_code == 403
    assert error.value.code == "forbidden"


def test_expired_oidc_token_is_rejected(rsa_key):
    with pytest.raises(auth.AuthError) as error:
        auth.verify_authentik_token(_token(rsa_key, expires_in=-10))
    assert error.value.code == "token_expired"


def test_wrong_oidc_audience_is_rejected(rsa_key):
    with pytest.raises(auth.AuthError) as error:
        auth.verify_authentik_token(_token(rsa_key, audience="other"))
    assert error.value.code == "invalid_audience"


def test_wrong_oidc_issuer_is_rejected(rsa_key):
    with pytest.raises(auth.AuthError) as error:
        auth.verify_authentik_token(_token(rsa_key, issuer="https://other.test/"))
    assert error.value.code == "invalid_issuer"


def test_valid_oidc_identity_still_verified(rsa_key):
    claims = auth.verify_authentik_token(_token(rsa_key))
    assert claims["sub"] == "user-123"
    assert claims["groups"] == [GROUP]


def test_write_without_csrf_header_is_rejected(api_client):
    response = api_client.post("/api/v1/jobs", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_header_missing"


def test_cross_origin_write_is_rejected(api_client):
    response = api_client.post(
        "/api/v1/jobs",
        json={},
        headers={"X-Requested-With": "tdl-web", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_origin_blocked"


def test_me_returns_validated_identity(api_client, native_pair):
    response = api_client.get("/api/v1/auth/me", headers=_auth(native_pair.access_token))
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["id"] == str(native_pair.user.id)
    assert body["name"] == "Admin"
    assert body["groups"] == []


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_rejects_old_schema_without_exposing_details(api_client, test_engine, path):
    from sqlalchemy import text

    with test_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'old_revision'"))
    response = api_client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_rejects_unavailable_database_without_exposing_credentials(api_client, monkeypatch, path):
    from sqlalchemy.exc import OperationalError

    from app import database

    def unavailable():
        raise OperationalError("postgresql://user:SECRET@host/db", {}, Exception("SECRET"))

    monkeypatch.setattr(database.engine, "connect", unavailable)
    response = api_client.get(path)
    assert response.status_code == 503
    assert "SECRET" not in response.text
