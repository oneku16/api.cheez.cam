import uuid
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key, salt="event-camera-session")


def create_session_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    return _serializer().dumps({"user_id": str(user_id)})


def load_session_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    max_age = settings.access_token_ttl_seconds
    try:
        data = _serializer().loads(token, max_age=max_age)
        return uuid.UUID(data["user_id"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None
