import secrets
import uuid
from datetime import UTC, datetime
from io import BytesIO

import qrcode
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_event_for_user
from app.api.schemas import QrCreate, QrOut, QrUpdate
from app.core.config import get_settings
from app.domain.enums import QrStatus
from app.domain.errors import NotFoundError
from app.infrastructure.db.models import Event, EventQrCode
from app.infrastructure.db.session import get_db

router = APIRouter(prefix="/api/events/{event_id}/qr", tags=["qr"])
settings = get_settings()


def _guest_url(event: Event, token: str) -> str:
    return f"{settings.frontend_base_url}/e/{event.slug}?token={token}"


def _get_active_qr(db: Session, event_id: uuid.UUID) -> EventQrCode | None:
    return (
        db.query(EventQrCode)
        .filter(EventQrCode.event_id == event_id, EventQrCode.status == QrStatus.ACTIVE)
        .order_by(EventQrCode.created_at.desc())
        .first()
    )


def _qr_out(event: Event, qr: EventQrCode) -> QrOut:
    return QrOut(
        id=qr.id,
        token=qr.token,
        url=_guest_url(event, qr.token),
        status=qr.status,
        valid_from=qr.valid_from,
        valid_until=qr.valid_until,
    )


@router.get("", response_model=QrOut)
def get_qr(
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    qr = _get_active_qr(db, event.id)
    if not qr:
        raise NotFoundError("QR_NOT_FOUND", "No active QR code.")
    return _qr_out(event, qr)


@router.post("", response_model=QrOut, status_code=201)
def create_qr(
    body: QrCreate,
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    existing = _get_active_qr(db, event.id)
    if existing:
        return _qr_out(event, existing)

    token = secrets.token_urlsafe(32)
    qr = EventQrCode(
        event_id=event.id,
        token=token,
        status=QrStatus.ACTIVE,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)
    return _qr_out(event, qr)


@router.patch("", response_model=QrOut)
def update_qr(
    body: QrUpdate,
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    qr = _get_active_qr(db, event.id)
    if not qr:
        raise NotFoundError("QR_NOT_FOUND", "No active QR code.")
    if body.valid_from is not None:
        qr.valid_from = body.valid_from
    if body.valid_until is not None:
        qr.valid_until = body.valid_until
    db.commit()
    db.refresh(qr)
    return _qr_out(event, qr)


@router.post("/revoke", response_model=QrOut)
def revoke_qr(
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    qr = _get_active_qr(db, event.id)
    if not qr:
        raise NotFoundError("QR_NOT_FOUND", "No active QR code.")
    qr.status = QrStatus.REVOKED
    qr.revoked_at = datetime.now(UTC)
    db.commit()
    db.refresh(qr)
    return _qr_out(event, qr)


@router.post("/regenerate", response_model=QrOut, status_code=201)
def regenerate_qr(
    body: QrCreate,
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    active = _get_active_qr(db, event.id)
    if active:
        active.status = QrStatus.REVOKED
        active.revoked_at = datetime.now(UTC)

    token = secrets.token_urlsafe(32)
    qr = EventQrCode(
        event_id=event.id,
        token=token,
        status=QrStatus.ACTIVE,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    db.add(qr)
    db.commit()
    db.refresh(qr)
    return _qr_out(event, qr)


@router.get("/download")
def download_qr_png(
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    qr = _get_active_qr(db, event.id)
    if not qr:
        raise NotFoundError("QR_NOT_FOUND", "No active QR code.")
    url = _guest_url(event, qr.token)
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
