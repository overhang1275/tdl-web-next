from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.schemas import DashboardRead, UserRead
from app.services.dashboard import dashboard_data

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardRead)
def dashboard(
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> DashboardRead:
    return DashboardRead(**dashboard_data(db))
