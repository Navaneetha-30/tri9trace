"""Application configuration loaded from environment / .env.

Centralizes secrets so the rest of the app never reads os.environ directly.
Ingestion and browse routes need NO external services; only the /generate
route needs GROQ_API_KEY (and MONGODB_URI for the Mongo-backed store).
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# Load .env once at import time. Safe to call multiple times.
load_dotenv()


class Settings:
    groq_api_key: str | None
    mongodb_uri: str | None
    groq_model: str
    sqlite_path: str

    def __init__(self) -> None:
        self.groq_api_key = os.environ.get("GROQ_API_KEY") or None
        self.mongodb_uri = os.environ.get("MONGODB_URI") or None
        self.groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        # SQLite file next to the repo root. Kept configurable for tests.
        self.sqlite_path = os.environ.get("CT200_SQLITE_PATH", "ct200_qa.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()