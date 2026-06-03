import uuid

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app.domain.errors import UnauthorizedError
from app.infrastructure.db.models import User
from app.infrastructure.db.session import get_db
from app.infrastructure.security.session import load_session_token

SESSION_COOKIE = "session"


def get_current_user(
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    if not session:
        raise UnauthorizedError()
    user_id = load_session_token(session)
    if not user_id:
        raise UnauthorizedError()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UnauthorizedError()
    return user


def get_event_for_user(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.infrastructure.db.models import Event

    event = (
        db.query(Event)
        .filter(
            Event.id == event_id,
            Event.organization_id == user.organization_id,
            Event.deleted_at.is_(None),
        )
        .first()
    )
    if not event:
        from app.domain.errors import NotFoundError

        raise NotFoundError("EVENT_NOT_FOUND", "Event not found.")
    return event
