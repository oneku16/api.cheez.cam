import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import EventStatus, QrStatus
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Event, EventQrCode, Organization
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

    assert client.post(url, json={"device_id": "device-a"}).status_code == 200
    assert client.post(url, json={"device_id": "device-b"}).status_code == 200

    r3 = client.post(url, json={"device_id": "device-c"})
    assert r3.status_code == 403
    assert r3.json()["error"]["code"] == "GUEST_LIMIT_REACHED"


def test_guest_limit_allows_returning_device(client, active_event_with_qr):
    slug = active_event_with_qr["slug"]
    token = active_event_with_qr["token"]
    url = f"/api/public/events/{slug}/guest-session?token={token}"

    client.post(url, json={"device_id": "device-a"})
    client.post(url, json={"device_id": "device-b"})

    r = client.post(url, json={"device_id": "device-a"})
    assert r.status_code == 200
    assert "guest_id" in r.json()
