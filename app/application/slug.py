import re
import uuid

from sqlalchemy.orm import Session

from app.infrastructure.db.models import Event

_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    base = _slug_re.sub("-", title.lower().strip()).strip("-")
    return base[:200] or "event"


def unique_slug(db: Session, title: str) -> str:
    base = slugify(title)
    candidate = base
    n = 0
    while db.query(Event).filter(Event.slug == candidate).first():
        n += 1
        candidate = f"{base}-{n}" if n < 10 else f"{base}-{uuid.uuid4().hex[:8]}"
    return candidate
