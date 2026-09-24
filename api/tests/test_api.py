"""API behaviour when dependencies fail - uses fakes, no real Postgres/Redis needed.

TestClient is used without `with`, so the startup hook (which waits for Postgres) doesn't run.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import get_db


class FailingSession:
    """A DB session whose commit fails with the given error."""

    def __init__(self, error):
        self.error = error

    def add(self, obj):
        pass

    async def commit(self):
        raise self.error


@pytest.fixture
def client():
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()


def use_session(error):
    async def fake_get_db():
        yield FailingSession(error)

    main.app.dependency_overrides[get_db] = fake_get_db


def metric(client, name):
    return client.get("/health").json()["metrics"][name]


@pytest.fixture(autouse=True)
def healthy_dependencies(monkeypatch):
    async def up():
        return True

    monkeypatch.setattr(main, "check_db", up)
    monkeypatch.setattr(main, "check_redis", up)


@pytest.mark.parametrize("error", [ConnectionRefusedError("refused"), TimeoutError("timed out")])
def test_postgres_unreachable_is_503_not_a_bug(client, error):
    use_session(error)
    unavailable_before, errors_before = metric(client, "db_unavailable"), metric(client, "errors")

    response = client.post("/shorten", json={"url": "https://example.com"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Database temporarily unavailable"}
    assert metric(client, "db_unavailable") == unavailable_before + 1
    assert metric(client, "errors") == errors_before  # not counted as our bug


def test_other_errors_are_still_500_bugs(client):
    use_session(ValueError("a real bug"))
    errors_before = metric(client, "errors")

    response = client.post("/shorten", json={"url": "https://example.com"})

    assert response.status_code == 500
    assert metric(client, "errors") == errors_before + 1


def test_health_answers_fast_when_postgres_hangs(client, monkeypatch):
    async def hangs():
        await asyncio.sleep(30)
        return True

    monkeypatch.setattr(main, "check_db", hangs)
    monkeypatch.setattr(main, "HEALTH_CHECK_TIMEOUT_SECONDS", 0.2)

    start = time.monotonic()
    response = client.get("/health")

    assert time.monotonic() - start < 2
    assert response.status_code == 503
    assert response.json()["postgres"] is False


def test_redis_down_only_keeps_health_200(client, monkeypatch):
    async def down():
        return False

    monkeypatch.setattr(main, "check_redis", down)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["redis"] is False
