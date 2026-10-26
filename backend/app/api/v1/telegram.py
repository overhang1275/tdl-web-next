from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.errors import ApiError
from app.schemas import LoginInput, UserRead
from app.services.interactive_login import interactive_login_service

router = APIRouter(prefix="/telegram/login", tags=["telegram"])


def _status() -> dict:
    session = interactive_login_service.status()
    return {
        "running": session.running,
        "output": session.output[-300:],
        "returncode": session.returncode,
        "error": session.error,
        "started_at": session.started_at,
        "finished_at": session.finished_at,
    }


@router.get("")
def login_status(_: UserRead = Depends(get_current_user)) -> dict:
    return _status()


@router.post("/start")
def login_start(_: UserRead = Depends(get_current_user)) -> dict:
    try:
        interactive_login_service.start()
    except RuntimeError as exc:
        raise ApiError("login_unavailable", str(exc), 503) from exc
    return _status()


@router.post("/input")
def login_input(
    payload: LoginInput,
    _: UserRead = Depends(get_current_user),
) -> dict:
    try:
        interactive_login_service.send(payload.value)
    except RuntimeError as exc:
        raise ApiError("login_not_running", str(exc), 409) from exc
    return _status()


@router.post("/cancel")
def login_cancel(_: UserRead = Depends(get_current_user)) -> dict:
    interactive_login_service.cancel()
    return _status()
