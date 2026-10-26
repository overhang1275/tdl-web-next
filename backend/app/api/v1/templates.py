from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import ApiError
from app.database import get_db
from app.models import DownloadTemplate, MediaType
from app.schemas import ConfirmRequest, TemplateCreate, TemplateRead, UserRead

router = APIRouter(prefix="/templates", tags=["templates"])


def template_read(template: DownloadTemplate) -> TemplateRead:
    return TemplateRead(
        id=template.id,
        name=template.name,
        chat_id=template.chat_id,
        chat_title=template.chat_title,
        hashtag=template.hashtag,
        media_type=template.media_type.value,
        search_text=template.search_text,
        date_from=template.date_from,
        date_to=template.date_to,
        skip_same=template.skip_same,
        refresh_export=template.refresh_export,
        export_only=template.export_only,
        output_subfolder=template.output_subfolder,
        created_at=template.created_at,
    )


@router.get("", response_model=list[TemplateRead])
def list_templates(
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> list[TemplateRead]:
    templates = list(
        db.scalars(
            select(DownloadTemplate).order_by(DownloadTemplate.created_at.desc())
        ).all()
    )
    return [template_read(template) for template in templates]


@router.post("", response_model=TemplateRead, status_code=201)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> TemplateRead:
    template = DownloadTemplate(
        name=payload.name.strip(),
        chat_id=payload.chat_id,
        chat_title=payload.chat_title,
        hashtag=payload.hashtag,
        media_type=MediaType(payload.media_type),
        search_text=payload.search_text,
        date_from=payload.date_from,
        date_to=payload.date_to,
        skip_same=payload.skip_same,
        refresh_export=payload.refresh_export,
        export_only=payload.export_only,
        output_subfolder=payload.output_subfolder,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template_read(template)


@router.put("/{template_id}", response_model=TemplateRead)
def update_template(
    template_id: int,
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> TemplateRead:
    template = db.get(DownloadTemplate, template_id)
    if template is None:
        raise ApiError("template_not_found", "La plantilla no existe.", 404)
    template.name = payload.name.strip()
    template.chat_id = payload.chat_id
    template.chat_title = payload.chat_title
    template.hashtag = payload.hashtag
    template.media_type = MediaType(payload.media_type)
    template.search_text = payload.search_text
    template.date_from = payload.date_from
    template.date_to = payload.date_to
    template.skip_same = payload.skip_same
    template.refresh_export = payload.refresh_export
    template.export_only = payload.export_only
    template.output_subfolder = payload.output_subfolder
    db.commit()
    db.refresh(template)
    return template_read(template)


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    payload: ConfirmRequest,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> None:
    if not payload.confirm:
        raise ApiError("confirmation_required", "Confirma la eliminación.", 400)
    template = db.get(DownloadTemplate, template_id)
    if template is None:
        raise ApiError("template_not_found", "La plantilla no existe.", 404)
    db.delete(template)
    db.commit()
