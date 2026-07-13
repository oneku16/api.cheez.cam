import uuid

from sqlalchemy.orm import Session, joinedload

from app.application.access import require_guest_access
from app.application.photos_admin import _apply_photo_deletions
from app.domain.enums import PhotoStatus
from app.domain.errors import AppError, NotFoundError
from app.infrastructure.db.models import Event, EventQrCode, Guest, Photo
from app.infrastructure.storage.r2 import StorageService


def _verify_guest(db: Session, event_id: uuid.UUID, guest_id: uuid.UUID) -> Guest:
    guest = (
        db.query(Guest)
        .filter(Guest.id == guest_id, Guest.event_id == event_id)
        .first()
    )
    if not guest:
        raise NotFoundError("GUEST_NOT_FOUND", "Guest session not found.")
    return guest


def list_guest_photos(db: Session, event: Event, guest_id: uuid.UUID) -> list[Photo]:
    _verify_guest(db, event.id, guest_id)
    return (
        db.query(Photo)
        .options(joinedload(Photo.guest))
        .filter(
            Photo.event_id == event.id,
            Photo.guest_id == guest_id,
            Photo.deleted_at.is_(None),
            Photo.completed_at.isnot(None),
            Photo.status.notin_([PhotoStatus.DELETED, PhotoStatus.FAILED]),
        )
        .order_by(Photo.created_at.desc())
        .all()
    )


def guest_remove_photos(
    db: Session,
    event: Event,
    qr: EventQrCode,
    guest_id: uuid.UUID,
    photo_ids: list[uuid.UUID],
) -> tuple[int, int]:
    require_guest_access(db, event, qr)
    guest = _verify_guest(db, event.id, guest_id)

    if not photo_ids:
        raise AppError("VALIDATION_ERROR", "No photos selected.", 400)

    photos = (
        db.query(Photo)
        .filter(
            Photo.event_id == event.id,
            Photo.guest_id == guest_id,
            Photo.id.in_(photo_ids),
            Photo.deleted_at.is_(None),
            Photo.completed_at.isnot(None),
        )
        .all()
    )
    if not photos:
        raise AppError("PHOTOS_NOT_FOUND", "No matching photos to remove.", 404)

    removed = _apply_photo_deletions(db, event, photos)
    db.commit()
    db.refresh(guest)
    remaining = max(0, event.max_photos_per_guest - guest.uploaded_count)
    return removed, remaining


def photo_to_urls(photo: Photo, storage: StorageService) -> tuple[str | None, str | None]:
    thumb_key = photo.thumbnail_object_key or photo.compressed_object_key or photo.original_object_key
    preview_key = photo.compressed_object_key or photo.original_object_key
    thumb_url = None
    preview_url = None
    try:
        if thumb_key:
            thumb_url = storage.create_presigned_read_url(thumb_key)
        if preview_key:
            preview_url = storage.create_presigned_read_url(preview_key)
    except Exception:
        pass
    return thumb_url, preview_url
