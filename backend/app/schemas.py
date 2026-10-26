from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MediaTypeLiteral = Literal["all", "video", "image", "audio", "document"]


class JobCreate(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    chat_title: str | None = Field(default=None, max_length=255)
    hashtag: str | None = Field(default=None, max_length=128)
    media_type: MediaTypeLiteral = "all"
    search_text: str | None = Field(default=None, max_length=255)
    date_from: date | None = None
    date_to: date | None = None
    skip_same: bool = True
    refresh_export: bool = True
    export_only: bool = False
    output_subfolder: str = Field(min_length=1, max_length=128)

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str) -> str:
        value = value.strip()
        if not value.lstrip("-").isdigit() and not value.startswith("@"):
            raise ValueError("chat_id must be numeric or an @username")
        return value

    @field_validator("hashtag")
    @classmethod
    def normalize_hashtag(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if not value:
            return None
        return value if value.startswith("#") else f"#{value}"

    @field_validator("output_subfolder")
    @classmethod
    def validate_output_subfolder(cls, value: str) -> str:
        from app.services.paths import sanitize_subfolder

        return sanitize_subfolder(value)

    @model_validator(mode="after")
    def validate_date_range(self) -> JobCreate:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before or equal to date_to")
        return self


class UserRead(BaseModel):
    username: str
    email: str | None = None
    name: str | None = None
    groups: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class StatusRead(BaseModel):
    environment: str
    version: str
    session_active: bool
    session_error: str | None = None
    tdl_installed: bool
    tdl_binary: str
    redis_connected: bool
    redis_error: str | None = None
    worker_connected: bool
    worker_count: int
    storage: str
    can_start_services: bool
    authentik_configured: bool


class Page[T](BaseModel):
    items: list[T]
    page: int
    per_page: int
    total: int
    page_count: int


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

