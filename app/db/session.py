"""SQLAlchemy engine + session factory against a local SQLite file.

create_all() is called on startup so a fresh clone needs no migration step.
The DB path is configurable via CT200_SQLITE_PATH (see app.config).
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

# check_same_thread=False: FastAPI may use threads; we run single-writer.
engine = create_engine(
    f"sqlite:///{settings.sqlite_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def init_db() -> None:
    """Create all tables. Idempotent."""
    # Import here so models register on Base before create_all.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency yielding a session, closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()