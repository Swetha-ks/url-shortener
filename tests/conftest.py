import os

# Must be set before the app is imported so tests use a throwaway SQLite file
# and the in-memory cache instead of real services.
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["REDIS_URL"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-for-tests-only-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.cache import get_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    """Fresh tables, empty cache and default limits for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    get_store().clear()
    settings = get_settings()
    original = (settings.create_limit_per_minute, settings.login_limit_per_minute)
    yield
    settings.create_limit_per_minute, settings.login_limit_per_minute = original


@pytest.fixture(scope="session", autouse=True)
def remove_test_db():
    yield
    engine.dispose()
    if os.path.exists("test.db"):
        os.remove("test.db")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def make_headers(client):
    """Returns a function that registers + logs in a user and gives auth headers."""

    def _make(email: str = "user@example.com", password: str = "password123") -> dict:
        client.post("/auth/register", json={"email": email, "password": password})
        response = client.post("/auth/login", data={"username": email, "password": password})
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _make


@pytest.fixture
def auth_headers(make_headers):
    return make_headers()
