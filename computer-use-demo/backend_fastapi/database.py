from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from .models import Base

logger = logging.getLogger(__name__)

# Resolve SQLite path from this package so it does not depend on uvicorn cwd.
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_DEFAULT_SQLITE_PATH = _REPO_ROOT / "computer_use_demo.db"


def _default_sqlite_url() -> str:
    return f"sqlite:///{_DEFAULT_SQLITE_PATH.resolve().as_posix()}"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_sqlite_url()


def _create_engine():
    url = DATABASE_URL
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
    return create_engine(url, pool_pre_ping=True)


engine = _create_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_sessions_columns() -> None:
    """Add columns introduced after first deploy (SQLite / simple ALTER)."""
    insp = inspect(engine)
    if not insp.has_table("sessions"):
        return
    existing = {c["name"] for c in insp.get_columns("sessions")}
    stmts: list[str] = []
    if "agent_api_port" not in existing:
        stmts.append("ALTER TABLE sessions ADD COLUMN agent_api_port INTEGER")
    if "docker_container_id" not in existing:
        stmts.append("ALTER TABLE sessions ADD COLUMN docker_container_id VARCHAR(128)")
    if "api_key" not in existing:
        stmts.append("ALTER TABLE sessions ADD COLUMN api_key TEXT")
    if "anthropic_base_url" not in existing:
        stmts.append("ALTER TABLE sessions ADD COLUMN anthropic_base_url VARCHAR(512)")
    if "api_endpoint" not in existing:
        stmts.append("ALTER TABLE sessions ADD COLUMN api_endpoint VARCHAR(16)")
    if not stmts:
        return
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))


def init_db() -> None:
    if DATABASE_URL.startswith("sqlite"):
        logger.info("SQLite database file: %s", DATABASE_URL.replace("sqlite:///", "", 1))
    Base.metadata.create_all(bind=engine)
    _migrate_sessions_columns()


def get_db() -> Generator[OrmSession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
