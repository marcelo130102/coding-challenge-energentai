from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from backend_fastapi.database import get_db
from backend_fastapi.models import Base
from backend_fastapi.routers.chat_ws import router as chat_ws_router
from backend_fastapi.routers.sessions import router as sessions_router


@pytest.fixture(autouse=True)
def _default_no_docker_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPUTER_USE_ORCHESTRATION", "false")


@pytest.fixture
def with_docker_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPUTER_USE_ORCHESTRATION", "true")
    # Fernet key for tests (orchestrated sessions require encrypted-at-rest credentials).
    monkeypatch.setenv(
        "SESSION_API_KEY_FERNET_KEY", Fernet.generate_key().decode("ascii")
    )


@pytest.fixture
def test_fernet_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Deterministic key for crypto unit tests."""
    key = base64.urlsafe_b64encode(hashlib.sha256(b"test-secret").digest())
    monkeypatch.setenv("SESSION_API_KEY_FERNET_KEY", key.decode("ascii"))
    return key.decode("ascii")


@dataclass(frozen=True, slots=True)
class SessionsHarness:
    """In-memory SQLite app plus a factory for direct ORM reads in tests."""

    client: TestClient
    session_factory: sessionmaker[OrmSession]


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def sessions_harness() -> Iterator[SessionsHarness]:
    """REST `/api/sessions` only; SQLite in memory (no Docker)."""
    engine = _memory_engine()
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(sessions_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield SessionsHarness(client, session_local)

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sessions_client(sessions_harness: SessionsHarness) -> TestClient:
    return sessions_harness.client


@pytest.fixture
def chat_websocket_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Sessions + chat WebSocket; patches ``SessionLocal`` so WS handler uses test DB."""
    engine = _memory_engine()
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("backend_fastapi.database.SessionLocal", session_local)
    monkeypatch.setattr("backend_fastapi.routers.chat_ws.SessionLocal", session_local)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(sessions_router, prefix="/api")
    app.include_router(chat_ws_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
