from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_status
from app.schemas import StatusRead, UserRead

router = APIRouter(tags=["status"])


@router.get("/status", response_model=StatusRead)
def status(
    _: UserRead = Depends(get_current_user),
    data: dict = Depends(get_status),
) -> dict:
    return data
