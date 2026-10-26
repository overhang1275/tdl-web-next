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


class JobRead(BaseModel):
    id: int
    chat_id: str
    chat_title: str | None = None
    hashtag: str | None = None
    media_type: str
    search_text: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    skip_same: bool
    refresh_export: bool
    export_only: bool
    output_subfolder: str
    status: str
    stage: str
    total_filtered_messages: int
    total_downloaded_files: int
    total_failed_files: int
    transfer_initialized: bool
    downloaded_bytes: int
    total_expected_bytes: int | None = None
    speed_bps: int
    eta_seconds: int | None = None
    progress_percent: float | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_position: int | None = None
    deletion_requested: bool = False
    deletion_error: str | None = None


class JobFileRead(BaseModel):
    file_id: int | None = None
    message_id: str | None = None
    name: str
    relative_path: str
    size: int
    human_size: str
    kind: str
    modified_at: int
    modified_label: str
    can_preview: bool
    status: str | None = None
    attempts: int = 0
    last_error: str | None = None
    content_url: str
    download_url: str


class ChatRead(BaseModel):
    id: str
    title: str
    username: str = ""
    type: str = ""
    topics_count: int = 0


class ChatPage(BaseModel):
    items: list[ChatRead]
    page: int
    per_page: int
    total: int
    page_count: int
    q: str
    chat_type: str
    sort: str
    type_counts: dict[str, int]
    cached_at: datetime | None = None
    refreshed: bool = False


class ChatProfileRead(BaseModel):
    chat: ChatRead | None = None
    chat_id: str
    chat_title: str
    jobs: list[JobRead]
    export_exists: bool
    export_updated_at: datetime | None = None
    downloaded_files: int
    downloaded_size: str
    download_root: str


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    chat_id: str | None = Field(default=None, max_length=64)
    chat_title: str | None = Field(default=None, max_length=255)
    hashtag: str | None = Field(default=None, max_length=128)
    media_type: MediaTypeLiteral = "all"
    search_text: str | None = Field(default=None, max_length=255)
    date_from: date | None = None
    date_to: date | None = None
    skip_same: bool = True
    refresh_export: bool = False
    export_only: bool = False
    output_subfolder: str | None = Field(default=None, max_length=128)

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str | None) -> str | None:
        if not value:
            return None
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
        return value if value.startswith("#") else f"#{value}"

    @field_validator("output_subfolder")
    @classmethod
    def validate_subfolder(cls, value: str | None) -> str | None:
        if not value:
            return None
        from app.services.paths import sanitize_subfolder

        return sanitize_subfolder(value)

    @model_validator(mode="after")
    def validate_dates(self) -> TemplateCreate:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before or equal to date_to")
        return self


class TemplateRead(BaseModel):
    id: int
    name: str
    chat_id: str | None = None
    chat_title: str | None = None
    hashtag: str | None = None
    media_type: str
    search_text: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    skip_same: bool
    refresh_export: bool
    export_only: bool
    output_subfolder: str | None = None
    created_at: datetime


class DashboardRead(BaseModel):
    active_jobs: int
    failed_jobs: int
    downloaded_files: int
    disk_usage: str
    latest_errors: list[JobRead]
    chat_counts: dict[str, object]


class SearchItem(BaseModel):
    id: str | int
    title: str
    subtitle: str
    url: str
    download_url: str | None = None


class SearchRead(BaseModel):
    chats: list[SearchItem]
    jobs: list[SearchItem]
    files: list[SearchItem]


class ConfirmRequest(BaseModel):
    confirm: bool = False


class LoginInput(BaseModel):
    value: str = Field(min_length=1, max_length=256)


class ResetRequest(BaseModel):
    confirmation: str
    keep_session: bool = True


class LogRead(BaseModel):
    content: str
    truncated: bool


class IdempotentJobResponse(BaseModel):
    job: JobRead
    duplicate: bool = False


