import base64
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_event_for_user
from app.api.schemas import (
    CompleteUploadRequest,
    CompleteUploadResponse,
    PhotoBulkDownloadResponse,
    PhotoBulkRemoveResponse,
    GuestPhotoRemoveRequest,
    GuestPhotoRemoveResponse,
    PhotoBulkRequest,
    PhotoDownloadItem,
    PhotoListResponse,
    PhotoOut,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.application.photos_admin import presigned_downloads, soft_delete_photos
from app.application.photos_guest import guest_remove_photos, list_guest_photos, photo_to_urls
from app.domain.errors import AppError
from app.application.access import require_guest_access
from app.application.photos_upload import (
    complete_upload,
    get_event_and_qr_by_slug_token,
    request_upload_url,
)
from app.domain.enums import PhotoStatus
from app.infrastructure.db.models import Event, Photo
from app.infrastructure.db.session import get_db
from app.infrastructure.storage.r2 import StorageService

router = APIRouter(tags=["photos"])


@router.get("/api/events/{event_id}/photos", response_model=PhotoListResponse)
def list_photos(
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
    status: str | None = None,
    limit: int = Query(default=50, le=100),
    cursor: str | None = None,
):
    q = db.query(Photo).filter(
        Photo.event_id == event.id,
        Photo.deleted_at.is_(None),
        Photo.completed_at.isnot(None),
    )
    if status:
        q = q.filter(Photo.status == status)
    else:
        # Include processing photos after guest complete (worker may still be running)
        q = q.filter(Photo.status.notin_([PhotoStatus.DELETED, PhotoStatus.FAILED]))

    if cursor:
        cursor_dt = datetime.fromisoformat(base64.urlsafe_b64decode(cursor + "==").decode())
        q = q.filter(Photo.created_at < cursor_dt)

    photos = q.order_by(Photo.created_at.desc()).limit(limit + 1).all()
    has_more = len(photos) > limit
    items = photos[:limit]

    storage = StorageService()
    out_items: list[PhotoOut] = []
    for p in items:
        thumb_key = p.thumbnail_object_key or p.compressed_object_key or p.original_object_key
        preview_key = p.compressed_object_key or p.original_object_key
        thumb_url = None
        preview_url = None
        try:
            if thumb_key:
                thumb_url = storage.create_presigned_read_url(thumb_key)
            if preview_key:
                preview_url = storage.create_presigned_read_url(preview_key)
        except Exception:
            pass
        out_items.append(
            PhotoOut(
                id=p.id,
                status=p.status,
                thumbnail_url=thumb_url,
                preview_url=preview_url,
                created_at=p.created_at,
            )
        )

    next_cursor = None
    if has_more and items:
        raw = items[-1].created_at.isoformat().encode()
        next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return PhotoListResponse(items=out_items, next_cursor=next_cursor)


@router.post("/api/events/{event_id}/photos/bulk")
def bulk_photos(
    body: PhotoBulkRequest,
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    if body.action == "remove":
        removed = soft_delete_photos(db, event, body.photo_ids)
        return PhotoBulkRemoveResponse(removed=removed)
    if body.action == "download":
        items = presigned_downloads(db, event, body.photo_ids)
        return PhotoBulkDownloadResponse(
            items=[
                PhotoDownloadItem(photo_id=pid, url=url, filename=name)
                for pid, url, name in items
            ]
        )
    raise AppError("INVALID_ACTION", "Unsupported bulk action.", 400)


public_router = APIRouter(prefix="/api/public/events", tags=["public-photos"])


@public_router.post("/{slug}/photos/upload-url", response_model=UploadUrlResponse)
def upload_url(
    slug: str,
    body: UploadUrlRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    event, qr = get_event_and_qr_by_slug_token(db, slug, token)
    photo, upload_url, headers = request_upload_url(
        db, event, qr, body.guest_id, body.filename, body.mime_type, body.size_bytes
    )
    return UploadUrlResponse(
        photo_id=photo.id,
        upload_url=upload_url,
        object_key=photo.original_object_key,
        headers=headers,
    )


@public_router.post("/{slug}/photos/complete", response_model=CompleteUploadResponse)
def complete(
    slug: str,
    body: CompleteUploadRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    event, qr = get_event_and_qr_by_slug_token(db, slug, token)
    photo, remaining = complete_upload(
        db, event, qr, body.guest_id, body.photo_id, body.object_key
    )
    status = photo.status if photo.status != PhotoStatus.PROCESSING else PhotoStatus.PENDING
    return CompleteUploadResponse(
        photo_id=photo.id,
        status=status,
        remaining_count=remaining,
    )


@public_router.get("/{slug}/photos", response_model=PhotoListResponse)
def list_guest_photos_route(
    slug: str,
    guest_id: uuid.UUID = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    event, qr = get_event_and_qr_by_slug_token(db, slug, token)
    require_guest_access(db, event, qr)
    photos = list_guest_photos(db, event, guest_id)
    storage = StorageService()
    out_items: list[PhotoOut] = []
    for p in photos:
        thumb_url, preview_url = photo_to_urls(p, storage)
        out_items.append(
            PhotoOut(
                id=p.id,
                status=p.status,
                thumbnail_url=thumb_url,
                preview_url=preview_url,
                created_at=p.created_at,
            )
        )
    return PhotoListResponse(items=out_items)


@public_router.post("/{slug}/photos/remove", response_model=GuestPhotoRemoveResponse)
def remove_guest_photos(
    slug: str,
    body: GuestPhotoRemoveRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    event, qr = get_event_and_qr_by_slug_token(db, slug, token)
    removed, remaining = guest_remove_photos(db, event, qr, body.guest_id, body.photo_ids)
    return GuestPhotoRemoveResponse(removed=removed, remaining_count=remaining)
