from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.database import get_db
from app.schemas import UserRead
from app.services.auth import AuthError
from app.services.sessions import verify_session
from app.services.status import status_service
from app.services.tdl import TdlService


def get_current_user(request: Request, db: Session = Depends(get_db)) -> UserRead:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError("unauthorized", "Inicia sesión para continuar.", 401)
    try:
        user = verify_session(db, token)
        if user.must_change_password and (request.method, request.url.path) not in {
            ("GET", "/api/v1/auth/me"), ("POST", "/api/v1/auth/change-password"), ("POST", "/api/v1/auth/logout")
        }:
            raise ApiError("password_change_required", "Cambia la contraseña para continuar.", 403)
        return user
    except AuthError as exc:
        raise ApiError(exc.code, exc.message, exc.status_code) from exc


def get_tdl() -> TdlService:
    return TdlService()


def get_status() -> dict:
    return status_service.get()
