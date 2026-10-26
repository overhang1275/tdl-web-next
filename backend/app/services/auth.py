from __future__ import annotations

import threading

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.config import settings


class AuthError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_jwks_lock = threading.Lock()
_jwks_client: PyJWKClient | None = None
_jwks_url: str | None = None


def configured() -> bool:
    return bool(settings.authentik_issuer and settings.authentik_audience)


def _client() -> PyJWKClient:
    global _jwks_client, _jwks_url
    if not settings.authentik_jwks_url:
        raise AuthError("auth_not_configured", "Authentik no está configurado.", 503)
    with _jwks_lock:
        if _jwks_client is None or _jwks_url != settings.authentik_jwks_url:
            _jwks_client = PyJWKClient(
                settings.authentik_jwks_url,
                cache_keys=True,
                headers={"User-Agent": "TDL-Console/1.0"},
            )
            _jwks_url = settings.authentik_jwks_url
        return _jwks_client


def verify_authentik_token(token: str) -> dict:
    if not configured():
        raise AuthError("auth_not_configured", "Authentik no está configurado.", 503)
    try:
        signing_key = _client().get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.authentik_audience,
            issuer=settings.authentik_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token_expired", "La sesión expiró.") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("invalid_audience", "Token inválido.") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthError("invalid_issuer", "Token inválido.") from exc
    except (PyJWKClientError, jwt.PyJWTError) as exc:
        raise AuthError("invalid_token", "Token inválido.") from exc
    if settings.authentik_admin_group:
        groups = payload.get("groups") or []
        if settings.authentik_admin_group not in groups:
            raise AuthError("forbidden", "No tienes acceso a esta aplicación.", 403)
    return payload
