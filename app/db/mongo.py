"""Generation document store with a swappable backend.

TRD section 3: generations live in MongoDB. Per TRD section 1, if
MONGODB_URI is unset we fall back to a local JSON-file store behind the
SAME interface, so the rest of the app never knows which backend is active.

Robustness note (documented in APPROACH.md): we additionally fall back to the
JSON store if a Mongo URI is configured but the cluster is unreachable at
first use (e.g. the dev machine's IP is not in the Atlas Network Access
allowlist). This keeps the full flow runnable for a reviewer without Atlas
network access; it is one env flag (unsetting MONGODB_URI) away from
strict Mongo-only behaviour.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.config import get_settings


class GenerationStore(Protocol):
    def put(self, doc: dict[str, Any]) -> str: ...
    def get(self, gen_id: str) -> dict[str, Any] | None: ...
    def list_by_selection(self, selection_id: int) -> list[dict[str, Any]]: ...
    def list_by_node(self, node_id: int) -> list[dict[str, Any]]: ...


def _json_path() -> Path:
    return Path(os.environ.get("CT200_JSON_STORE", "generations.json"))


class JsonGenerationStore:
    """Process-local JSON-file store. Used when MONGODB_URI is unset or
    unreachable. Persisted to disk so generations survive restarts."""

    _lock = threading.Lock()

    def __init__(self) -> None:
        self._path = _json_path()

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, docs: list[dict[str, Any]]) -> None:
        self._path.write_text(json.dumps(docs, default=str), encoding="utf-8")

    def put(self, doc: dict[str, Any]) -> str:
        with self._lock:
            docs = self._load()
            gen_id = doc.get("_id") or str(uuid.uuid4())
            doc["_id"] = gen_id
            doc.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            docs.append(doc)
            self._save(docs)
        return gen_id

    def get(self, gen_id: str) -> dict[str, Any] | None:
        for d in self._load():
            if str(d.get("_id")) == str(gen_id):
                return d
        return None

    def list_by_selection(self, selection_id: int) -> list[dict[str, Any]]:
        return [d for d in self._load() if d.get("selection_id") == selection_id]

    def list_by_node(self, node_id: int) -> list[dict[str, Any]]:
        out = []
        for d in self._load():
            for pin in d.get("source_pins", []):
                if pin.get("node_id") == node_id:
                    out.append(d)
                    break
        return out


class MongoGenerationStore:
    """pymongo-backed store. Lazily connects; if the first operation cannot
    reach the cluster, raises ConnectionError so the factory can fall back."""

    def __init__(self) -> None:
        uri = get_settings().mongodb_uri
        if not uri:
            raise RuntimeError("MONGODB_URI is not set")
        from pymongo import MongoClient

        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._coll = self._client["ct200_qa"]["generations"]

    def _ping(self) -> None:
        self._client.admin.command("ping")

    def put(self, doc: dict[str, Any]) -> str:
        doc = dict(doc)
        doc.setdefault("created_at", datetime.now(timezone.utc))
        result = self._coll.insert_one(doc)
        return str(result.inserted_id)

    def get(self, gen_id: str) -> dict[str, Any] | None:
        from bson import ObjectId

        try:
            return self._coll.find_one({"_id": ObjectId(gen_id)})
        except Exception:
            return None

    def list_by_selection(self, selection_id: int) -> list[dict[str, Any]]:
        return list(self._coll.find({"selection_id": selection_id}))

    def list_by_node(self, node_id: int) -> list[dict[str, Any]]:
        return list(self._coll.find({"source_pins.node_id": node_id}))


_store: GenerationStore | None = None


def get_generation_store() -> GenerationStore:
    """Factory: Mongo when configured AND reachable, else JSON file.

    The choice is made once per process and cached. A failed Mongo ping logs
    a clear message and falls back, so a reviewer without Atlas access still
    gets the full flow (with provenance intact, just on disk instead of Mongo).
    """
    global _store
    if _store is not None:
        return _store
    uri = get_settings().mongodb_uri
    if uri:
        try:
            store = MongoGenerationStore()
            store._ping()
            print("[store] using MongoDB")
            _store = store
            return _store
        except Exception as exc:  # noqa: BLE001
            print(f"[store] MongoDB unreachable ({type(exc).__name__}); falling back to JSON store. "
                  f"Add this machine's IP to the Atlas Network Access allowlist to use Mongo.")
    else:
        print("[store] MONGODB_URI not set; using JSON store")
    _store = JsonGenerationStore()
    return _store