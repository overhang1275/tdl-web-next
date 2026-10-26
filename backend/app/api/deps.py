from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request

from app.api.errors import ApiError
from app.schemas import UserRead
from app.services.auth import AuthError, verify_authentik_token
from app.services.status import status_service
from app.services.tdl import TdlService


def get_current_user(request: Request) -> UserRead:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError("unauthorized", "Inicia sesión para continuar.", 401)
    try:
        payload = verify_authentik_token(token)
    except AuthError as exc:
        raise ApiError(exc.code, exc.message, exc.status_code) from exc
    return UserRead(
        username=str(
            payload.get("preferred_username")
            or payload.get("email")
            or payload.get("sub", "")
        ),
        email=payload.get("email"),
        name=payload.get("name"),
        groups=list(payload.get("groups") or []),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
    )


def get_tdl() -> TdlService:
    return TdlService()


def get_status() -> dict:
    return status_service.get()
