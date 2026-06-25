from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domain.enums import AccessStatus, EventStatus, QrStatus
from app.domain.errors import AppError
from app.infrastructure.db.models import Event, EventQrCode


ACCESS_MESSAGES = {
    AccessStatus.NOT_FOUND: "Event not found.",
    AccessStatus.NOT_PUBLISHED: "This event is not open yet.",
    AccessStatus.NOT_STARTED: "This event is not open yet. Please come back later.",
    AccessStatus.EXPIRED: "This event has ended. Photo uploads are no longer available.",
    AccessStatus.REVOKED: "This QR code is no longer active.",
    AccessStatus.ARCHIVED: "This event is no longer available.",
    AccessStatus.UPLOADS_DISABLED: "Photo uploads are temporarily disabled.",
}


class AccessResult:
    def __init__(self, status: AccessStatus, message: str | None = None):
        self.status = status
        self.message = message or ACCESS_MESSAGES.get(status)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate_guest_access(
    db: Session,
    event: Event | None,
    qr: EventQrCode | None,
    *,
    now: datetime | None = None,
) -> AccessResult:
    now = now or datetime.now(UTC)
    now = _as_aware_utc(now)

    if event is None or qr is None:
        return AccessResult(AccessStatus.NOT_FOUND)

    if event.deleted_at is not None or event.status == EventStatus.ARCHIVED:
        return AccessResult(AccessStatus.ARCHIVED)

    if event.status != EventStatus.ACTIVE:
        return AccessResult(AccessStatus.NOT_PUBLISHED)

    if not event.uploads_enabled:
        return AccessResult(AccessStatus.UPLOADS_DISABLED)

    if event.starts_at and now < _as_aware_utc(event.starts_at):
        return AccessResult(AccessStatus.NOT_STARTED)

    if event.ends_at and now > _as_aware_utc(event.ends_at):
        return AccessResult(AccessStatus.EXPIRED)

    if qr.status == QrStatus.REVOKED or qr.revoked_at is not None:
        return AccessResult(AccessStatus.REVOKED)

    if qr.valid_from and now < _as_aware_utc(qr.valid_from):
        return AccessResult(AccessStatus.NOT_STARTED)

    if qr.valid_until and now > _as_aware_utc(qr.valid_until):
        return AccessResult(AccessStatus.EXPIRED)

    if qr.status != QrStatus.ACTIVE:
        return AccessResult(AccessStatus.REVOKED)

    return AccessResult(AccessStatus.ALLOWED)


def is_final_upload_window(
    event: Event | None,
    qr: EventQrCode | None,
    *,
    now: datetime | None = None,
) -> bool:
    if event is None or qr is None:
        return False
    if event.deleted_at is not None or event.status == EventStatus.ARCHIVED:
        return False
    if event.status != EventStatus.ACTIVE or not event.uploads_enabled:
        return False
    if qr.status != QrStatus.ACTIVE or qr.revoked_at is not None:
        return False

    now = _as_aware_utc(now or datetime.now(UTC))
    deadlines = [dt for dt in (event.ends_at, qr.valid_until) if dt is not None]
    return any(_as_aware_utc(deadline) < now for deadline in deadlines)


def require_guest_access(
    db: Session,
    event: Event | None,
    qr: EventQrCode | None,
    *,
    allow_final_upload: bool = False,
) -> AccessResult:
    result = evaluate_guest_access(db, event, qr)
    if result.status != AccessStatus.ALLOWED and allow_final_upload:
        if is_final_upload_window(event, qr):
            return AccessResult(AccessStatus.ALLOWED)
    if result.status != AccessStatus.ALLOWED:
        code_map = {
            AccessStatus.NOT_FOUND: "EVENT_NOT_FOUND",
            AccessStatus.NOT_PUBLISHED: "EVENT_NOT_PUBLISHED",
            AccessStatus.NOT_STARTED: "EVENT_NOT_STARTED",
            AccessStatus.EXPIRED: "QR_EXPIRED",
            AccessStatus.REVOKED: "QR_REVOKED",
            AccessStatus.ARCHIVED: "EVENT_NOT_FOUND",
            AccessStatus.UPLOADS_DISABLED: "UPLOADS_DISABLED",
        }
        raise AppError(code_map.get(result.status, "FORBIDDEN"), result.message or "", 403)
    return result
