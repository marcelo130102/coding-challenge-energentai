from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from .models import Base

logger = logging.getLogger(__name__)

# Resolve SQLite path from this package so it does not depend on uvicorn cwd.
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_DEFAULT_SQLITE_PATH = _REPO_ROOT / "computer_use_demo.db"


def _default_sqlite_url() -> str:
    return f"sqlite:///{_DEFAULT_SQLITE_PATH.resolve().as_posix()}"


def _sqlite_db_path_from_url(url_str: str) -> Path | None:
    """Absolute filesystem path for a file-based SQLite URL, or None if not applicable."""
    if not url_str.startswith("sqlite"):
        return None
    try:
        url = make_url(url_str)
    except Exception:
        return None
    if not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _ensure_sqlite_file_exists(url_str: str) -> None:
    """Create parent directory and empty DB file if missing (e.g. after /data fallback)."""
    path = _sqlite_db_path_from_url(url_str)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def _resolved_database_url() -> str:
    """Pick DATABASE_URL, ensure SQLite parent dirs exist, fall back if /data is unusable (local dev).

    Non-SQLite URLs (e.g. ``postgresql+psycopg2://...``) are returned unchanged for production.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        return _default_sqlite_url()
    if not raw.startswith("sqlite"):
        return raw

    try:
        url = make_url(raw)
    except Exception:
        return raw

    if not url.database or url.database == ":memory:":
        return raw

    path = Path(url.database)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Typical when .env copies Docker's sqlite:////data/... on a Mac host.
        if path.is_absolute() and str(path).startswith("/data"):
            logger.warning(
                "DATABASE_URL directory not usable (%s: %s). Using default %s.",
                path.parent,
                exc,
                _DEFAULT_SQLITE_PATH,
            )
            return _default_sqlite_url()
        raise

    return raw


DATABASE_URL = _resolved_database_url()
_ensure_sqlite_file_exists(DATABASE_URL)


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


def _migrate_messages_columns() -> None:
    """Add columns introduced after first deploy (SQLite / simple ALTER)."""
    insp = inspect(engine)
    if not insp.has_table("messages"):
        return
    existing = {c["name"] for c in insp.get_columns("messages")}
    if "message_kind" not in existing:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE messages ADD COLUMN message_kind VARCHAR(32) "
                    "NOT NULL DEFAULT 'chat'",
                ),
            )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_sessions_columns()
    _migrate_messages_columns()


def get_db() -> Generator[OrmSession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
