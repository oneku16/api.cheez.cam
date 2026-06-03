import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.db.base import Base
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


def test_register_and_me(client):
    r = client.post(
        "/api/auth/register",
        json={
            "organization_name": "Test Org",
            "full_name": "Test User",
            "email": "test@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "test@example.com"

    r2 = client.get("/api/auth/me")
    assert r2.status_code == 200
    assert r2.json()["organization"]["name"] == "Test Org"
