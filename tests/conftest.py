"""Shared pytest fixtures.

Each test gets a throwaway SQLite file (patched onto app.db.session) so the
real ct200_qa.db is never touched and tests are fully isolated. The JSON
generation store is also pointed at a temp file.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app.db import session as s

    path = tmp_path / "test.db"
    eng = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    factory = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    monkeypatch.setattr(s, "engine", eng)
    monkeypatch.setattr(s, "SessionLocal", factory)
    s.Base.metadata.create_all(bind=eng)

    sess = factory()
    monkeypatch.setenv("CT200_JSON_STORE", str(tmp_path / "gens.json"))
    yield sess
    sess.close()