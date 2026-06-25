import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str

    model_config = {"from_attributes": True}


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut


class EventCreate(BaseModel):
    title: str
    description: str | None = None
    rules: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_photos_per_guest: int = Field(default=10, ge=1, le=25)
    max_guests: int = Field(default=100, ge=1)


class EventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    rules: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_photos_per_guest: int | None = Field(default=None, ge=1, le=25)
    max_guests: int | None = Field(default=None, ge=1)
    uploads_enabled: bool | None = None
    status: str | None = None
    theme_color: str | None = None


class EventOut(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    status: str
    description: str | None = None
    rules: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_photos_per_guest: int
    max_guests: int
    uploads_enabled: bool
    theme_color: str | None = None

    model_config = {"from_attributes": True}


class EventDetailOut(EventOut):
    total_photos: int = 0
    unique_guests: int = 0


class QrCreate(BaseModel):
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class QrUpdate(BaseModel):
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class QrOut(BaseModel):
    id: uuid.UUID
    token: str
    url: str
    status: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    model_config = {"from_attributes": True}


class AccessOut(BaseModel):
    status: str
    message: str | None = None


class PublicEventOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    rules: str | None = None
    ends_at: datetime | None = None
    qr_valid_until: datetime | None = None
    max_photos_per_guest: int
    max_guests: int
    uploads_enabled: bool


class PublicEventResponse(BaseModel):
    event: PublicEventOut | None = None
    access: AccessOut


class GuestSessionRequest(BaseModel):
    device_id: str


class GuestSessionResponse(BaseModel):
    guest_id: uuid.UUID
    uploaded_count: int
    remaining_count: int


class UploadUrlRequest(BaseModel):
    guest_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    final_upload: bool = False


class UploadUrlResponse(BaseModel):
    photo_id: uuid.UUID
    upload_url: str
    object_key: str
    headers: dict[str, str]


class CompleteUploadRequest(BaseModel):
    guest_id: uuid.UUID
    photo_id: uuid.UUID
    object_key: str
    final_upload: bool = False


class CompleteUploadResponse(BaseModel):
    photo_id: uuid.UUID
    status: str
    remaining_count: int


class PhotoOut(BaseModel):
    id: uuid.UUID
    status: str
    thumbnail_url: str | None = None
    preview_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PhotoListResponse(BaseModel):
    items: list[PhotoOut]
    next_cursor: str | None = None


class PhotoBulkRequest(BaseModel):
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    action: Literal["remove", "download"]


class PhotoBulkRemoveResponse(BaseModel):
    removed: int


class PhotoDownloadItem(BaseModel):
    photo_id: uuid.UUID
    url: str
    filename: str


class PhotoBulkDownloadResponse(BaseModel):
    items: list[PhotoDownloadItem]


class GuestPhotoRemoveRequest(BaseModel):
    guest_id: uuid.UUID
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=25)


class GuestPhotoRemoveResponse(BaseModel):
    removed: int
    remaining_count: int
