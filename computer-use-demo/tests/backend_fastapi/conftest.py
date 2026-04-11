from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend_fastapi.database import get_db
from backend_fastapi.models import Base
from backend_fastapi.routers.sessions import router


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


@pytest.fixture
def sessions_client() -> TestClient:
    """App solo con rutas /api/sessions y BD SQLite en memoria (sin Docker)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()
