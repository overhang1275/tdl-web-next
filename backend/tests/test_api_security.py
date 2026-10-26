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


def test_docker_refuses_unmounted_database_path(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEPLOYMENT_MODE", "docker")
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "mounted"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'outside' / 'app.sqlite'}")
    monkeypatch.setenv("AUTHENTIK_ISSUER", ISSUER)
    monkeypatch.setenv("AUTHENTIK_AUDIENCE", AUDIENCE)
    with pytest.raises(RuntimeError, match="DATABASE_DIR"):
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
def api_client(monkeypatch):
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
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(
        claims,
        rsa_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def test_valid_authentik_token_is_accepted(api_client, rsa_key):
    response = api_client.get("/api/v1/status", headers=_auth(_token(rsa_key)))
    assert response.status_code == 200
    assert response.json()["authentik_configured"] is True


def test_missing_group_is_forbidden(api_client, rsa_key):
    response = api_client.get("/api/v1/status", headers=_auth(_token(rsa_key, groups=())))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_expired_token_is_rejected(api_client, rsa_key):
    response = api_client.get(
        "/api/v1/status", headers=_auth(_token(rsa_key, expires_in=-10))
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_wrong_audience_is_rejected(api_client, rsa_key):
    response = api_client.get(
        "/api/v1/status", headers=_auth(_token(rsa_key, audience="other"))
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_audience"


def test_wrong_issuer_is_rejected(api_client, rsa_key):
    response = api_client.get(
        "/api/v1/status", headers=_auth(_token(rsa_key, issuer="https://other.test/"))
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_issuer"


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


def test_me_returns_validated_identity(api_client, rsa_key):
    response = api_client.get("/api/v1/auth/me", headers=_auth(_token(rsa_key)))
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["email"] == "admin@example.com"
    assert body["groups"] == [GROUP]
