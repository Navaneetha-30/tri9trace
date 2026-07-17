"""Staleness detection tests (FR6).

Uses the REAL v1/v2 manuals so the stale/not-stale assertions are the real
answers: Safety Limits changed (160->140 bpm) so it goes stale; Introduction
is byte-identical across both versions so it stays fresh.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

VALID = json.dumps(
    {
        "test_cases": [
            {"title": f"c{i}", "steps": ["s"], "expected_result": "e", "rationale": "r", "source_node_ids": []}
            for i in range(3)
        ]
    }
)


def _setup(client, responses):
    from app.main import app
    from app.deps import get_llm, get_store
    from app.llm.client import FakeLLM
    from app.db.mongo import JsonGenerationStore

    app.dependency_overrides[get_llm] = lambda: FakeLLM(responses)
    app.dependency_overrides[get_store] = lambda: JsonGenerationStore()


def _ingest(client, which):
    f = "ct200_manual.md" if which == 1 else "ct200_manual_v2.md"
    client.post("/documents/ingest", json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / f)})


def _section_id(client, name, version=1):
    return [s for s in client.get(f"/documents/ct200-manual/sections?version={version}").json() if s["heading_text"] == name][0]["node_id"]


def test_stale_when_source_text_changed(client):
    """Generate from Safety Limits (v1: 160 bpm), ingest v2 (140 bpm), recompute:
    the generation must be stale with a diff summary referencing the change."""
    from app.versioning.staleness import compute_staleness
    from app.db.session import SessionLocal

    _setup(client, [VALID])
    _ingest(client, 1)
    sl = _section_id(client, "Safety Limits")
    sel = client.post("/selections", json={"name": "safety", "node_ids": [sl], "version": 1}).json()
    gen = client.post(f"/selections/{sel['id']}/generate").json()

    # Still v1 -> not stale.
    db = SessionLocal()
    st = compute_staleness(db, gen)
    assert st["stale"] is False
    assert st["stale_nodes"] == []

    # Ingest v2 -> Safety Limits text changed -> stale.
    _ingest(client, 2)
    st2 = compute_staleness(db, gen)
    db.close()
    assert st2["stale"] is True
    assert sl in st2["stale_nodes"]
    summary = st2["diff_summaries"][sl]
    assert summary  # non-empty
    assert "140" in summary or "160" in summary


def test_not_stale_when_source_text_unchanged(client):
    """Introduction is byte-identical in v1 and v2, so a generation pinned to it
    stays fresh after re-ingest."""
    from app.versioning.staleness import compute_staleness
    from app.db.session import SessionLocal

    _setup(client, [VALID])
    _ingest(client, 1)
    intro = _section_id(client, "Introduction")
    sel = client.post("/selections", json={"name": "intro", "node_ids": [intro], "version": 1}).json()
    gen = client.post(f"/selections/{sel['id']}/generate").json()

    _ingest(client, 2)
    db = SessionLocal()
    st = compute_staleness(db, gen)
    db.close()
    assert st["stale"] is False, st
    assert st["stale_nodes"] == []


def test_stale_when_node_removed_in_current_version(client):
    """Cleaning exists in v1 but is removed in v2; a generation pinned to it
    must be flagged stale (node removed)."""
    from app.versioning.staleness import compute_staleness
    from app.db.session import SessionLocal

    _setup(client, [VALID])
    _ingest(client, 1)
    hits = client.get("/nodes/search?q=Cleaning&document_id=1&version=1").json()
    cleaning = [h for h in hits if h["heading_text"] == "Cleaning"][0]["node_id"]
    sel = client.post("/selections", json={"name": "clean", "node_ids": [cleaning], "version": 1}).json()
    gen = client.post(f"/selections/{sel['id']}/generate").json()

    _ingest(client, 2)
    db = SessionLocal()
    st = compute_staleness(db, gen)
    db.close()
    assert st["stale"] is True
    assert cleaning in st["stale_nodes"]
    assert "removed" in st["diff_summaries"][cleaning]