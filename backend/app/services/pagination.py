from __future__ import annotations

from typing import Any


def _page(total: int, per_page: int, page: int) -> dict[str, int]:
    page_count = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), page_count)
    return {"page": page, "per_page": per_page, "page_count": page_count}


def chat_type_group(chat: dict) -> str:
    value = str(chat.get("type") or "").lower()
    if "channel" in value:
        return "channel"
    if "group" in value:
        return "group"
    if "private" in value or "user" in value:
        return "private"
    return "other"


def chat_search_text(chat: dict) -> str:
    values = [chat.get("id"), chat.get("title"), chat.get("visible_name"), chat.get("username"), chat.get("type")]
    return " ".join(str(value).lower() for value in values if value)


def chat_display_name(chat: dict) -> str:
    return str(
        chat.get("title")
        or chat.get("visible_name")
        or chat.get("username")
        or chat.get("id")
        or ""
    ).lower()


def paginate_chats(
    chats: list[dict],
    q: str,
    page: int,
    per_page: int,
    chat_type: str = "",
    sort: str = "json",
) -> dict[str, Any]:
    options = [10, 25, 50, 100]
    per_page = per_page if per_page in options else 25
    chat_type = chat_type if chat_type in {"", "channel", "group", "private"} else ""
    sort = sort if sort in {"json", "name", "type", "id"} else "json"
    q = q.strip()
    filtered = [chat for chat in chats if q.lower() in chat_search_text(chat)] if q else chats
    type_counts = {"channel": 0, "group": 0, "private": 0, "other": 0}
    for chat in filtered:
        group = chat_type_group(chat)
        type_counts[group] = type_counts.get(group, 0) + 1
    if chat_type:
        filtered = [chat for chat in filtered if chat_type_group(chat) == chat_type]
    if sort == "type":
        order = {"channel": 0, "group": 1, "private": 2, "other": 3}
        filtered = sorted(
            filtered, key=lambda chat: (order.get(chat_type_group(chat), 9), chat_display_name(chat))
        )
    elif sort == "id":
        filtered = sorted(filtered, key=lambda chat: str(chat.get("id") or ""))
    elif sort == "name":
        filtered = sorted(filtered, key=chat_display_name)
    total = len(filtered)
    meta = _page(total, per_page, page)
    page = meta["page"]
    start = (page - 1) * per_page
    return {
        "items": filtered[start : start + per_page],
        "q": q,
        "chat_type": chat_type,
        "sort": sort,
        "type_counts": type_counts,
        "total": total,
        "page": page,
        "per_page": per_page,
        "page_count": meta["page_count"],
        "start": start + 1 if total else 0,
        "end": min(start + per_page, total),
    }


def paginate_files(
    files: list[dict],
    q: str,
    kind: str,
    sort: str,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    options = [12, 24, 48, 96]
    per_page = per_page if per_page in options else 24
    kind = kind if kind in {"", "image", "video", "audio", "pdf", "text", "file"} else ""
    sort = sort if sort in {"name", "date-desc", "size-desc", "size-asc"} else "name"
    q = q.strip().lower()
    filtered = files
    if q:
        filtered = [item for item in filtered if q in str(item["relative_path"]).lower()]
    if kind:
        filtered = [item for item in filtered if item["kind"] == kind]
    if sort == "date-desc":
        filtered = sorted(
            filtered,
            key=lambda item: (int(item["modified_at"]), str(item["relative_path"]).lower()),
            reverse=True,
        )
    elif sort == "size-desc":
        filtered = sorted(
            filtered,
            key=lambda item: (int(item["size"]), str(item["relative_path"]).lower()),
            reverse=True,
        )
    elif sort == "size-asc":
        filtered = sorted(
            filtered,
            key=lambda item: (int(item["size"]), str(item["relative_path"]).lower()),
        )
    else:
        filtered = sorted(filtered, key=lambda item: str(item["relative_path"]).lower())
    total = len(filtered)
    meta = _page(total, per_page, page)
    page = meta["page"]
    start = (page - 1) * per_page
    return {
        "items": filtered[start : start + per_page],
        "q": q,
        "kind": kind,
        "sort": sort,
        "total": total,
        "page": page,
        "per_page": per_page,
        "page_count": meta["page_count"],
        "start": start + 1 if total else 0,
        "end": min(start + per_page, total),
    }
