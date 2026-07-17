"""LLM generation API tests (FR5). Offline: a FakeLLM + JSON store injected
via dependency_overrides, so no Groq/Mongo calls. One live Groq smoke test is
documented in README, not run here."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

VALID = json.dumps(
    {
        "test_cases": [
            {
                "title": f"Case {i}",
                "steps": [f"step {i}"],
                "expected_result": f"expected {i}",
                "rationale": f"why {i}",
                "source_node_ids": [],
            }
            for i in range(1, 4)
        ]
    }
)
MALFORMED = "not json at all {{"
WRONG_SHAPE = json.dumps({"test_cases": [{"title": "x"}]})  # missing fields + count


def _setup(client, responses):
    from app.main import app
    from app.deps import get_llm, get_store
    from app.llm.client import FakeLLM
    from app.db.mongo import JsonGenerationStore

    app.dependency_overrides[get_llm] = lambda: FakeLLM(responses)
    app.dependency_overrides[get_store] = lambda: JsonGenerationStore()


def _ingest_and_select(client):
    client.post("/documents/ingest", json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual.md")})
    sl = [s for s in client.get("/documents/ct200-manual/sections").json() if s["heading_text"] == "Safety Limits"][0]["node_id"]
    sel = client.post("/selections", json={"name": "safety", "node_ids": [sl], "version": 1}).json()
    return sel["id"]


def test_generate_happy_path(client):
    _setup(client, [VALID])
    sel_id = _ingest_and_select(client)
    r = client.post(f"/selections/{sel_id}/generate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse_status"] == "ok"
    assert body["retry_count"] == 0
    assert 3 <= len(body["test_cases"]) <= 5
    assert len(body["source_pins"]) == 1
    assert body["generation_index"] == 0
    assert body["model"]


def test_generate_retry_then_ok(client):
    _setup(client, [MALFORMED, VALID])
    sel_id = _ingest_and_select(client)
    r = client.post(f"/selections/{sel_id}/generate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse_status"] == "retried_ok"
    assert body["retry_count"] == 1
    assert len(body["test_cases"]) == 3


def test_generate_failed_returns_502_and_is_inspectable(client):
    _setup(client, [MALFORMED, MALFORMED])
    sel_id = _ingest_and_select(client)
    r = client.post(f"/selections/{sel_id}/generate")
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert detail["parse_status"] == "failed"
    gen_id = detail["generation_id"]
    # The failed generation is still stored and retrievable (never swallowed).
    got = client.get(f"/generations/{gen_id}").json()
    assert got["parse_status"] == "failed"
    assert got["test_cases"] == []
    assert got["raw_response"] == MALFORMED


def test_duplicate_submission_creates_new_generation(client):
    _setup(client, [VALID, VALID])
    sel_id = _ingest_and_select(client)
    g1 = client.post(f"/selections/{sel_id}/generate").json()
    g2 = client.post(f"/selections/{sel_id}/generate").json()
    assert g1["id"] != g2["id"]
    assert g1["generation_index"] == 0
    assert g2["generation_index"] == 1
    listed = client.get("/generations", params={"selection_id": sel_id}).json()
    assert len(listed) == 2


def test_provenance_pinned_to_v1_content_hash(client):
    _setup(client, [VALID])
    sel_id = _ingest_and_select(client)
    gen = client.post(f"/selections/{sel_id}/generate").json()
    pin = gen["source_pins"][0]
    # The pinned hash must equal the v1 revision's hash for that node.
    node = client.get(f"/nodes/{pin['node_id']}?version=1").json()
    assert pin["content_hash"] == node["content_hash"]
    assert "160 bpm" in pin["body_text"]


def test_list_generations_by_node(client):
    _setup(client, [VALID])
    sel_id = _ingest_and_select(client)
    gen = client.post(f"/selections/{sel_id}/generate").json()
    node_id = gen["source_pins"][0]["node_id"]
    by_node = client.get("/generations", params={"node_id": node_id}).json()
    assert len(by_node) == 1
    assert by_node[0]["id"] == gen["id"]