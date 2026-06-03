import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.domain.enums import PhotoStatus
from app.domain.errors import AppError
from app.infrastructure.db.models import Event, Guest, Photo
from app.infrastructure.storage.r2 import StorageService


def _object_keys_for_photo(photo: Photo) -> list[str]:
    keys: list[str] = []
    for key in (
        photo.original_object_key,
        photo.compressed_object_key,
        photo.thumbnail_object_key,
    ):
        if key and key not in keys:
            keys.append(key)
    return keys


def _photos_for_event(
    db: Session, event_id: uuid.UUID, photo_ids: list[uuid.UUID]
) -> list[Photo]:
    if not photo_ids:
        return []
    return (
        db.query(Photo)
        .filter(
            Photo.event_id == event_id,
            Photo.id.in_(photo_ids),
            Photo.deleted_at.is_(None),
            Photo.completed_at.isnot(None),
        )
        .all()
    )


def _apply_photo_deletions(db: Session, event: Event, photos: list[Photo]) -> int:
    storage = StorageService()
    keys_to_delete: list[str] = []
    for photo in photos:
        if photo.status != PhotoStatus.DELETED:
            keys_to_delete.extend(_object_keys_for_photo(photo))
    storage.delete_objects(keys_to_delete)

    now = datetime.now(UTC)
    removed = 0
    decrement_by_guest: dict[uuid.UUID, int] = {}

    for photo in photos:
        if photo.status == PhotoStatus.DELETED:
            continue
        photo.status = PhotoStatus.DELETED
        photo.deleted_at = now
        removed += 1
        decrement_by_guest[photo.guest_id] = decrement_by_guest.get(photo.guest_id, 0) + 1

    for guest_id, count in decrement_by_guest.items():
        guest = db.query(Guest).filter(Guest.id == guest_id, Guest.event_id == event.id).first()
        if guest:
            guest.uploaded_count = max(0, guest.uploaded_count - count)

    return removed


def soft_delete_photos(db: Session, event: Event, photo_ids: list[uuid.UUID]) -> int:
    photos = _photos_for_event(db, event.id, photo_ids)
    if not photos:
        raise AppError("PHOTOS_NOT_FOUND", "No matching photos to remove.", 404)

    removed = _apply_photo_deletions(db, event, photos)
    db.commit()
    return removed


def presigned_downloads(
    db: Session, event: Event, photo_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, str, str]]:
    photos = _photos_for_event(db, event.id, photo_ids)
    if not photos:
        raise AppError("PHOTOS_NOT_FOUND", "No matching photos to download.", 404)

    storage = StorageService()
    items: list[tuple[uuid.UUID, str, str]] = []
    for photo in photos:
        key = photo.original_object_key or photo.compressed_object_key
        if not key:
            continue
        ext = Path(key).suffix or ".jpg"
        filename = f"{photo.id}{ext}"
        url = storage.create_presigned_read_url(key, expires_in=3600)
        items.append((photo.id, url, filename))

    if not items:
        raise AppError("DOWNLOAD_UNAVAILABLE", "Selected photos have no stored files yet.", 400)

    return items
