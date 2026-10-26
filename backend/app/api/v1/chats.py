from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import ApiError
from app.config import settings
from app.database import get_db
from app.schemas import (
    ChatPage,
    ChatProfileRead,
    ChatRead,
    ConfirmRequest,
    UserRead,
)
from app.services.chat_cache import (
    ChatsRefreshInProgress,
    read_chats_cache,
    refresh_chats_cache,
)
from app.services.chats import chat_profile_data
from app.services.pagination import paginate_chats
from app.services.paths import chat_path_key, safe_child
from app.services.tdl import TdlError

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=ChatPage)
def list_chats(
    refresh: bool = False,
    q: str = "",
    chat_type: str = "",
    sort: str = "json",
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    _: UserRead = Depends(get_current_user),
) -> ChatPage:
    refreshed = False
    error: str | None = None
    try:
        if refresh:
            chats, cached_at = refresh_chats_cache(wait=False)
            refreshed = True
        else:
            chats, cached_at = read_chats_cache()
            if not cached_at:
                chats, cached_at = refresh_chats_cache()
                refreshed = True
    except TdlError as exc:
        chats, cached_at = read_chats_cache()
        error = str(exc)
    except ChatsRefreshInProgress as exc:
        chats, cached_at = read_chats_cache()
        error = str(exc)
    if error and not cached_at:
        raise ApiError("chats_unavailable", error, 502)
    pagination = paginate_chats(
        chats, q=q, page=page, per_page=per_page, chat_type=chat_type, sort=sort
    )
    items = [
        ChatRead(
            id=str(chat.get("id") or ""),
            title=str(chat.get("title") or chat.get("visible_name") or "Sin nombre"),
            username=str(chat.get("username") or ""),
            type=str(chat.get("type") or ""),
            topics_count=len(chat.get("topics") or []),
        )
        for chat in pagination["items"]
    ]
    return ChatPage(
        items=items,
        page=pagination["page"],
        per_page=pagination["per_page"],
        total=pagination["total"],
        page_count=pagination["page_count"],
        q=pagination["q"],
        chat_type=pagination["chat_type"],
        sort=pagination["sort"],
        type_counts=pagination["type_counts"],
        cached_at=cached_at,
        refreshed=refreshed,
    )


@router.get("/{chat_id}", response_model=ChatProfileRead)
def get_chat(
    chat_id: str,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> ChatProfileRead:
    return chat_profile_data(db, chat_id)


@router.delete("/{chat_id}/downloads", status_code=204)
def clean_chat_downloads(
    chat_id: str,
    payload: ConfirmRequest,
    _: UserRead = Depends(get_current_user),
) -> None:
    if not payload.confirm:
        raise ApiError("confirmation_required", "Confirma la limpieza.", 400)
    try:
        root = safe_child(settings.downloads_dir, chat_path_key(chat_id))
    except ValueError as exc:
        raise ApiError("invalid_chat", "Chat inválido.", 400) from exc
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
