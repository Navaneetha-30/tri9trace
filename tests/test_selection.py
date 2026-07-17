"""Selection API tests (FR4): version pinning survives re-ingest."""
from __future__ import annotations

from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def _ingest_v1(client):
    r = client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual.md")},
    )
    assert r.status_code == 200


def _safety_id(client, version=1):
    r = client.get(f"/documents/ct200-manual/sections?version={version}")
    return [s for s in r.json() if s["heading_text"] == "Safety Limits"][0]["node_id"]


def test_create_selection_is_version_pinned(client):
    _ingest_v1(client)
    sl = _safety_id(client)
    r = client.post("/selections", json={"name": "safety", "node_ids": [sl], "version": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pinned_version"] is not None
    assert any(n["heading_text"] == "Safety Limits" for n in body["nodes"])
    assert "160 bpm" in body["nodes"][0]["body_text"]


def test_selection_pinned_text_survives_reingest(client):
    """A selection pinned to v1 must still show v1 text after v2 is ingested,
    even though v2's Safety Limits text changed."""
    _ingest_v1(client)
    sl = _safety_id(client)
    sel = client.post("/selections", json={"name": "safety", "node_ids": [sl], "version": 1}).json()
    # Now ingest v2 (Safety Limits -> 140 bpm / 7 kg).
    client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual_v2.md")},
    )
    # Re-fetch the selection: must still show v1's 160 bpm text.
    got = client.get(f"/selections/{sel['id']}").json()
    assert got["pinned_version"] is not None
    assert "160 bpm" in got["nodes"][0]["body_text"]
    assert "140 bpm" not in got["nodes"][0]["body_text"]


def test_selection_rejects_removed_node_at_version(client):
    """Cleaning is removed in v2; pinning it to v2 must 400 with 'removed'."""
    _ingest_v1(client)
    client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual_v2.md")},
    )
    hits = client.get("/nodes/search?q=Cleaning&document_id=1&version=1").json()
    cleaning_id = [h for h in hits if h["heading_text"] == "Cleaning"][0]["node_id"]
    r = client.post("/selections", json={"name": "x", "node_ids": [cleaning_id], "version": 2})
    assert r.status_code == 400
    assert "removed" in r.json()["detail"]


def test_selection_rejects_cross_document_nodes(client):
    _ingest_v1(client)
    a = _safety_id(client)
    client.post(
        "/documents/ingest",
        json={"slug": "other-doc", "title": "Other", "file_path": str(DATA / "ct200_manual.md")},
    )
    other_sections = client.get("/documents/other-doc/sections").json()
    other_id = other_sections[0]["node_id"]
    r = client.post("/selections", json={"name": "x", "node_ids": [a, other_id]})
    assert r.status_code == 400
    assert "same document" in r.json()["detail"]