import pytest
from datetime import UTC, datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import EventStatus, PhotoStatus, QrStatus
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Event, EventQrCode, Guest, Organization, Photo
from app.infrastructure.db.session import get_db
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def active_event_with_qr():
    db = TestingSessionLocal()
    org = Organization(name="Test Org")
    db.add(org)
    db.flush()

    event = Event(
        organization_id=org.id,
        title="Party",
        slug="party",
        status=EventStatus.ACTIVE,
        max_photos_per_guest=10,
        max_guests=2,
        uploads_enabled=True,
    )
    db.add(event)
    db.flush()

    token = "test-token-123"
    qr = EventQrCode(event_id=event.id, token=token, status=QrStatus.ACTIVE)
    db.add(qr)
    db.commit()
    slug = event.slug
    db.close()

    return {"slug": slug, "token": token}


def test_guest_limit_blocks_new_device(client, active_event_with_qr):
    slug = active_event_with_qr["slug"]
    token = active_event_with_qr["token"]
    url = f"/api/public/events/{slug}/guest-session?token={token}"

    assert client.post(url, json={"device_id": "device-a", "guest_name": "Alan"}).status_code == 200
    assert client.post(url, json={"device_id": "device-b", "guest_name": "Lora"}).status_code == 200

    r3 = client.post(url, json={"device_id": "device-c", "guest_name": "Casey"})
    assert r3.status_code == 403
    assert r3.json()["error"]["code"] == "GUEST_LIMIT_REACHED"


def test_guest_limit_allows_returning_device(client, active_event_with_qr):
    slug = active_event_with_qr["slug"]
    token = active_event_with_qr["token"]
    url = f"/api/public/events/{slug}/guest-session?token={token}"

    client.post(url, json={"device_id": "device-a", "guest_name": "Alan"})
    client.post(url, json={"device_id": "device-b", "guest_name": "Lora"})

    r = client.post(url, json={"device_id": "device-a"})
    assert r.status_code == 200
    body = r.json()
    assert "guest_id" in body
    assert body["guest_name"] == "Alan"


def test_guest_session_requires_name_for_new_guest(client, active_event_with_qr):
    slug = active_event_with_qr["slug"]
    token = active_event_with_qr["token"]
    url = f"/api/public/events/{slug}/guest-session?token={token}"

    missing = client.post(url, json={"device_id": "device-a"})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "GUEST_NAME_REQUIRED"

    blank = client.post(url, json={"device_id": "device-a", "guest_name": "   "})
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "GUEST_NAME_REQUIRED"

    ok = client.post(url, json={"device_id": "device-a", "guest_name": "  Alan  "})
    assert ok.status_code == 200
    assert ok.json()["guest_name"] == "Alan"


def test_guest_session_requires_name_for_legacy_guest_without_display_name(
    client, active_event_with_qr
):
    slug = active_event_with_qr["slug"]
    token = active_event_with_qr["token"]
    url = f"/api/public/events/{slug}/guest-session?token={token}"

    db = TestingSessionLocal()
    event = db.query(Event).filter(Event.slug == slug).one()
    db.add(Guest(event_id=event.id, device_id="legacy-device"))
    db.commit()
    db.close()

    missing = client.post(url, json={"device_id": "legacy-device"})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "GUEST_NAME_REQUIRED"

    ok = client.post(url, json={"device_id": "legacy-device", "guest_name": "Legacy"})
    assert ok.status_code == 200
    assert ok.json()["guest_name"] == "Legacy"


def test_public_event_allows_returning_guest_after_qr_deadline_for_final_upload(client):
    db = TestingSessionLocal()
    org = Organization(name="Test Org")
    db.add(org)
    db.flush()

    event = Event(
        organization_id=org.id,
        title="Party",
        slug="party-grace",
        status=EventStatus.ACTIVE,
        max_photos_per_guest=10,
        max_guests=2,
        uploads_enabled=True,
    )
    db.add(event)
    db.flush()

    valid_until = datetime.now(UTC) - timedelta(seconds=30)
    token = "expired-token-123"
    qr = EventQrCode(
        event_id=event.id,
        token=token,
        status=QrStatus.ACTIVE,
        valid_until=valid_until,
    )
    db.add(qr)
    db.add(Guest(event_id=event.id, device_id="device-a", display_name="Alan"))
    db.commit()
    slug = event.slug
    db.close()

    session_url = f"/api/public/events/{slug}/guest-session?token={token}"
    session_res = client.post(session_url, json={"device_id": "device-a"})
    assert session_res.status_code == 200
    assert session_res.json()["guest_name"] == "Alan"

    event_res = client.get(f"/api/public/events/{slug}?token={token}")
    assert event_res.status_code == 200
    body = event_res.json()
    assert body["access"]["status"] == "allowed"
    assert body["event"]["qr_valid_until"] is not None


def test_admin_photo_list_includes_author_name(client, active_event_with_qr):
    slug = active_event_with_qr["slug"]

    reg = client.post(
        "/api/auth/register",
        json={
            "full_name": "Admin User",
            "email": "admin-photos@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert reg.status_code == 200

    db = TestingSessionLocal()
    event = db.query(Event).filter(Event.slug == slug).one()
    # Move event into the registered user's org so admin photo list can see it
    from app.infrastructure.db.models import User

    user = db.query(User).filter(User.email == "admin-photos@example.com").one()
    event.organization_id = user.organization_id
    guest = Guest(event_id=event.id, device_id="device-author", display_name="Alan")
    db.add(guest)
    db.flush()
    photo = Photo(
        event_id=event.id,
        guest_id=guest.id,
        status=PhotoStatus.PENDING,
        original_object_key="events/test/original.jpg",
        completed_at=datetime.now(UTC),
    )
    db.add(photo)
    db.commit()
    event_id = str(event.id)
    db.close()

    res = client.get(f"/api/events/{event_id}/photos")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["author_name"] == "Alan"
