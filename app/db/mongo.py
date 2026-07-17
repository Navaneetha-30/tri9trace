"""Generation document store (TRD section 3 + section 1 fallback).

If MONGODB_URI is set, generations are stored in MongoDB. If it is unset,
generations are stored in a local JSON file. The rest of the app talks to the
same GenerationStore interface either way. This is the TRD-sanctioned simple
fallback; for this build the JSON store is the default.
"""
from __future__ import annotations

import json
import os
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
    """Local JSON-file store used when MONGODB_URI is not set."""

    def _load(self) -> list[dict[str, Any]]:
        if not _json_path().exists():
            return []
        try:
            return json.loads(_json_path().read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, docs: list[dict[str, Any]]) -> None:
        _json_path().write_text(json.dumps(docs, default=str), encoding="utf-8")

    def put(self, doc: dict[str, Any]) -> str:
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
    """pymongo-backed store used when MONGODB_URI is set."""

    def __init__(self) -> None:
        uri = get_settings().mongodb_uri
        if not uri:
            raise RuntimeError("MONGODB_URI is not set")
        from pymongo import MongoClient

        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._coll = self._client["ct200_qa"]["generations"]

    def put(self, doc: dict[str, Any]) -> str:
        doc = dict(doc)
        doc.setdefault("created_at", datetime.now(timezone.utc))
        return str(self._coll.insert_one(doc).inserted_id)

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
    """Mongo when MONGODB_URI is set, else the JSON file store."""
    global _store
    if _store is not None:
        return _store
    if get_settings().mongodb_uri:
        _store = MongoGenerationStore()
    else:
        _store = JsonGenerationStore()
    return _store