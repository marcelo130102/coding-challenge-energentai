from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from .models import Base

DEFAULT_SQLITE_URL = "sqlite:///./computer_use_demo.db"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)


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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[OrmSession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
