"""Retrieval API tests (FR7): staleness flag is queryable on every generation."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
VALID = json.dumps({"test_cases": [{"title": f"c{i}", "steps": ["s"], "expected_result": "e", "rationale": "r", "source_node_ids": []} for i in range(3)]})


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


def _safety(client):
    return [s for s in client.get("/documents/ct200-manual/sections").json() if s["heading_text"] == "Safety Limits"][0]["node_id"]


def test_staleness_inlined_in_list_and_single(client):
    _setup(client, [VALID])
    _ingest(client, 1)
    sl = _safety(client)
    sel = client.post("/selections", json={"name": "safety", "node_ids": [sl], "version": 1}).json()
    client.post(f"/selections/{sel['id']}/generate")

    # Before v2: not stale.
    lst = client.get("/generations", params={"selection_id": sel["id"]}).json()
    assert len(lst) == 1
    assert lst[0]["stale"] is False
    single = client.get(f"/generations/{lst[0]['id']}").json()
    assert single["stale"] is False
    assert single["diff_summary"] is None

    # After v2: stale, with a diff summary.
    _ingest(client, 2)
    lst2 = client.get("/generations", params={"selection_id": sel["id"]}).json()
    assert lst2[0]["stale"] is True
    assert sl in lst2[0]["stale_nodes"]
    single2 = client.get(f"/generations/{lst2[0]['id']}").json()
    assert single2["stale"] is True
    assert single2["diff_summary"]
    assert "160" in single2["diff_summary"] or "140" in single2["diff_summary"]


def test_retrieval_by_node_carries_staleness(client):
    _setup(client, [VALID])
    _ingest(client, 1)
    sl = _safety(client)
    sel = client.post("/selections", json={"name": "safety", "node_ids": [sl], "version": 1}).json()
    client.post(f"/selections/{sel['id']}/generate")
    _ingest(client, 2)
    by_node = client.get("/generations", params={"node_id": sl}).json()
    assert len(by_node) == 1
    assert by_node[0]["stale"] is True