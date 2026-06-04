import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_event_for_user
from app.api.schemas import EventCreate, EventDetailOut, EventOut, EventUpdate
from app.application.slug import unique_slug
from app.domain.enums import EventStatus
from app.infrastructure.db.models import Event, Guest, Photo, User
from app.infrastructure.db.session import get_db

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status: str | None = None,
):
    q = db.query(Event).filter(
        Event.organization_id == user.organization_id,
        Event.deleted_at.is_(None),
    )
    if status:
        q = q.filter(Event.status == status)
    events = q.order_by(Event.created_at.desc()).limit(50).all()
    return [EventOut.model_validate(e) for e in events]


@router.post("", response_model=EventOut, status_code=201)
def create_event(
    body: EventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    event = Event(
        organization_id=user.organization_id,
        title=body.title,
        description=body.description,
        rules=body.rules,
        slug=unique_slug(db, body.title),
        status=EventStatus.DRAFT,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        max_photos_per_guest=body.max_photos_per_guest,
        max_guests=body.max_guests,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return EventOut.model_validate(event)


@router.get("/{event_id}", response_model=EventDetailOut)
def get_event(event: Event = Depends(get_event_for_user), db: Session = Depends(get_db)):
    total_photos = (
        db.query(func.count(Photo.id))
        .filter(Photo.event_id == event.id, Photo.deleted_at.is_(None), Photo.completed_at.isnot(None))
        .scalar()
        or 0
    )
    unique_guests = (
        db.query(func.count(Guest.id)).filter(Guest.event_id == event.id).scalar() or 0
    )
    out = EventDetailOut.model_validate(event)
    out.total_photos = total_photos
    out.unique_guests = unique_guests
    return out


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    body: EventUpdate,
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] == EventStatus.ACTIVE:
        pass
    for key, value in data.items():
        setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return EventOut.model_validate(event)


@router.delete("/{event_id}", response_model=EventOut)
def archive_event(
    event: Event = Depends(get_event_for_user),
    db: Session = Depends(get_db),
):
    event.status = EventStatus.ARCHIVED
    event.deleted_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return EventOut.model_validate(event)
