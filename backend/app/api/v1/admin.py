from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import ApiError
from app.database import get_db
from app.schemas import ResetRequest, UserRead
from app.services.admin import reset_application_state

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset")
def reset(
    payload: ResetRequest,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> dict:
    if payload.confirmation.strip() != "REINICIAR":
        raise ApiError(
            "confirmation_required",
            "Escribe REINICIAR para confirmar.",
            400,
        )
    return reset_application_state(db, keep_session=payload.keep_session)
