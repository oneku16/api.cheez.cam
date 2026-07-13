from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import (
    AccessOut,
    GuestSessionRequest,
    GuestSessionResponse,
    PublicEventOut,
    PublicEventResponse,
)
from app.application.access import evaluate_guest_access, is_final_upload_window
from app.application.photos_upload import get_event_and_qr_by_slug_token
from app.domain.enums import AccessStatus
from app.domain.errors import AppError
from app.infrastructure.db.models import Guest
from app.infrastructure.db.session import get_db

router = APIRouter(prefix="/api/public/events", tags=["public"])


def _normalize_guest_name(guest_name: str | None) -> str | None:
    if guest_name is None:
        return None
    trimmed = guest_name.strip()
    if not trimmed:
        return None
    return trimmed[:100]


@router.get("/{slug}", response_model=PublicEventResponse)
def get_public_event(
    slug: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    try:
        event, qr = get_event_and_qr_by_slug_token(db, slug, token)
    except Exception:
        return PublicEventResponse(
            event=None,
            access=AccessOut(status=AccessStatus.NOT_FOUND, message="Event not found."),
        )

    result = evaluate_guest_access(db, event, qr)
    final_upload = is_final_upload_window(event, qr)
    if result.status != AccessStatus.ALLOWED and not final_upload:
        return PublicEventResponse(
            event=None,
            access=AccessOut(status=result.status, message=result.message),
        )

    return PublicEventResponse(
        event=PublicEventOut(
            id=event.id,
            title=event.title,
            description=event.description,
            rules=event.rules,
            ends_at=event.ends_at,
            qr_valid_until=qr.valid_until,
            max_photos_per_guest=event.max_photos_per_guest,
            max_guests=event.max_guests,
            uploads_enabled=event.uploads_enabled,
        ),
        access=AccessOut(status=AccessStatus.ALLOWED),
    )


@router.post("/{slug}/guest-session", response_model=GuestSessionResponse)
def guest_session(
    slug: str,
    body: GuestSessionRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    event, qr = get_event_and_qr_by_slug_token(db, slug, token)
    result = evaluate_guest_access(db, event, qr)
    final_upload = is_final_upload_window(event, qr)
    if result.status != AccessStatus.ALLOWED and not final_upload:
        raise AppError(
            result.status.upper(),
            result.message or "Access denied.",
            403,
        )

    guest = (
        db.query(Guest)
        .filter(Guest.event_id == event.id, Guest.device_id == body.device_id)
        .first()
    )
    normalized_name = _normalize_guest_name(body.guest_name)

    if not guest:
        if final_upload:
            raise AppError(
                "EVENT_EXPIRED",
                "This event has ended. Photo uploads are no longer available.",
                403,
            )
        if not normalized_name:
            raise AppError(
                "GUEST_NAME_REQUIRED",
                "Guest name is required.",
                400,
            )
        guest_count = (
            db.query(func.count(Guest.id)).filter(Guest.event_id == event.id).scalar() or 0
        )
        if guest_count >= event.max_guests:
            raise AppError(
                "GUEST_LIMIT_REACHED",
                "This event has reached its guest limit.",
                403,
            )
        guest = Guest(
            event_id=event.id,
            device_id=body.device_id,
            display_name=normalized_name,
        )
        db.add(guest)
    elif not guest.display_name:
        if not normalized_name:
            raise AppError(
                "GUEST_NAME_REQUIRED",
                "Guest name is required.",
                400,
            )
        guest.display_name = normalized_name
    elif normalized_name:
        guest.display_name = normalized_name

    guest.last_seen_at = datetime.now(UTC)
    db.commit()
    db.refresh(guest)

    remaining = max(0, event.max_photos_per_guest - guest.uploaded_count)
    return GuestSessionResponse(
        guest_id=guest.id,
        uploaded_count=guest.uploaded_count,
        remaining_count=remaining,
        guest_name=guest.display_name,
    )
