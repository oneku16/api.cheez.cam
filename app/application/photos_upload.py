import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.application.access import require_guest_access
from app.core.config import get_settings
from app.domain.enums import PhotoStatus
from app.domain.errors import AppError, NotFoundError
from app.infrastructure.db.models import Event, EventQrCode, Guest, Photo
from app.infrastructure.storage.r2 import StorageService

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def normalize_mime_type(mime_type: str, filename: str) -> str:
    mime = (mime_type or "").strip().lower()
    if mime in ALLOWED_MIME:
        return mime
    if mime in ("", "application/octet-stream"):
        ext = Path(filename).suffix.lower()
        return _EXT_TO_MIME.get(ext, mime)
    return mime


def _ext_for_mime(mime: str, filename: str) -> str:
    ext = mimetypes.guess_extension(mime) or Path(filename).suffix
    if ext in (".jpe", ".jpeg"):
        return ".jpg"
    if ext == ".heif":
        return ".heic"
    return ext or ".jpg"


def _original_key(event_id: uuid.UUID, photo_id: uuid.UUID, ext: str) -> str:
    return f"events/{event_id}/original/{photo_id}{ext}"


def validate_file_metadata(mime_type: str, size_bytes: int) -> None:
    settings = get_settings()
    if mime_type not in ALLOWED_MIME:
        raise AppError("INVALID_FILE_TYPE", "File type not allowed.", 400)
    if size_bytes <= 0 or size_bytes > settings.max_upload_size_bytes:
        raise AppError("FILE_TOO_LARGE", "File exceeds maximum upload size.", 400)


def get_event_and_qr_by_slug_token(
    db: Session, slug: str, token: str
) -> tuple[Event, EventQrCode]:
    event = db.query(Event).filter(Event.slug == slug, Event.deleted_at.is_(None)).first()
    if not event:
        raise NotFoundError("EVENT_NOT_FOUND", "Event not found.")
    qr = (
        db.query(EventQrCode)
        .filter(EventQrCode.event_id == event.id, EventQrCode.token == token)
        .first()
    )
    if not qr:
        raise NotFoundError("QR_NOT_FOUND", "QR code not found.")
    return event, qr


def request_upload_url(
    db: Session,
    event: Event,
    qr: EventQrCode,
    guest_id: uuid.UUID,
    filename: str,
    mime_type: str,
    size_bytes: int,
    *,
    final_upload: bool = False,
) -> tuple[Photo, str, dict]:
    require_guest_access(db, event, qr, allow_final_upload=final_upload)
    mime_type = normalize_mime_type(mime_type, filename)
    validate_file_metadata(mime_type, size_bytes)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.event_id == event.id).first()
    if not guest:
        raise NotFoundError("GUEST_NOT_FOUND", "Guest session not found.")

    remaining = event.max_photos_per_guest - guest.uploaded_count
    if remaining <= 0:
        raise AppError("PHOTO_LIMIT_REACHED", "Photo limit reached.", 403)

    photo_id = uuid.uuid4()
    ext = _ext_for_mime(mime_type, filename)
    object_key = _original_key(event.id, photo_id, ext)

    photo = Photo(
        id=photo_id,
        event_id=event.id,
        guest_id=guest.id,
        status=PhotoStatus.PROCESSING,
        original_object_key=object_key,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    storage = StorageService()
    upload_url = storage.create_presigned_upload_url(object_key)
    return photo, upload_url, {}


def complete_upload(
    db: Session,
    event: Event,
    qr: EventQrCode,
    guest_id: uuid.UUID,
    photo_id: uuid.UUID,
    object_key: str,
    *,
    final_upload: bool = False,
) -> tuple[Photo, int]:
    require_guest_access(db, event, qr, allow_final_upload=final_upload)

    photo = (
        db.query(Photo)
        .filter(Photo.id == photo_id, Photo.event_id == event.id, Photo.guest_id == guest_id)
        .first()
    )
    if not photo:
        raise NotFoundError("UPLOAD_NOT_FOUND", "Upload not found.")

    guest = db.query(Guest).filter(Guest.id == guest_id).with_for_update().first()
    if not guest:
        raise NotFoundError("GUEST_NOT_FOUND", "Guest not found.")

    if photo.completed_at is not None:
        remaining = event.max_photos_per_guest - guest.uploaded_count
        return photo, remaining

    if photo.status not in (PhotoStatus.PROCESSING,):
        if photo.status == PhotoStatus.FAILED:
            raise AppError("OBJECT_VERIFICATION_FAILED", "Upload failed.", 400)
        remaining = event.max_photos_per_guest - guest.uploaded_count
        photo.completed_at = photo.completed_at or datetime.now(UTC)
        return photo, remaining

    if photo.original_object_key != object_key:
        raise AppError("OBJECT_VERIFICATION_FAILED", "Object key mismatch.", 400)

    settings = get_settings()
    storage = StorageService()
    try:
        head = storage.head_object(object_key)
    except Exception as exc:
        photo.status = PhotoStatus.FAILED
        photo.upload_error = str(exc)
        db.commit()
        raise AppError("OBJECT_VERIFICATION_FAILED", "Object not found in storage.", 400) from exc

    content_length = head.get("ContentLength", 0)
    if content_length > settings.max_upload_size_bytes:
        photo.status = PhotoStatus.FAILED
        photo.upload_error = "File too large"
        db.commit()
        raise AppError("FILE_TOO_LARGE", "File exceeds maximum upload size.", 400)

    photo.size_bytes = content_length
    photo.completed_at = datetime.now(UTC)
    guest.uploaded_count += 1
    db.commit()
    db.refresh(photo)

    from app.workers.tasks import enqueue_image_processing

    enqueue_image_processing(str(photo.id))

    remaining = event.max_photos_per_guest - guest.uploaded_count
    return photo, remaining
