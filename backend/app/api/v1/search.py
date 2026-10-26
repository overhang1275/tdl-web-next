from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.schemas import SearchRead, UserRead
from app.services.search import global_search

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchRead)
def search(
    q: str = Query("", max_length=200),
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> SearchRead:
    return SearchRead(**global_search(db, q, limit))
