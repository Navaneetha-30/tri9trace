"""Browse API tests (FR3) via TestClient against the isolated temp DB."""
from __future__ import annotations

from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def _ingest_real(client):
    r = client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual.md")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_sections_lists_top_level(client):
    _ingest_real(client)
    r = client.get("/documents/ct200-manual/sections")
    assert r.status_code == 200
    sections = r.json()
    headings = [s["heading_text"] for s in sections]
    assert "Introduction" in headings
    assert "Safety Limits" in headings
    assert all(s["level"] == 2 for s in sections)


def test_get_node_returns_body_hash_and_children(client):
    _ingest_real(client)
    r = client.get("/documents/ct200-manual/sections")
    safety = [s for s in r.json() if s["heading_text"] == "Safety Limits"][0]
    node = client.get(f"/nodes/{safety['node_id']}").json()
    assert "160 bpm" in node["body_text"]
    assert node["content_hash"]
    # Operating Instructions should have children.
    op = [s for s in client.get("/documents/ct200-manual/sections").json() if s["heading_text"] == "Operating Instructions"][0]
    op_node = client.get(f"/nodes/{op['node_id']}").json()
    child_headings = [c["heading_text"] for c in op_node["children"]]
    assert "Starting a Session" in child_headings
    assert "Alarms" in child_headings


def test_version_query_param(client):
    _ingest_real(client)
    client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual_v2.md")},
    )
    r1 = client.get("/documents/ct200-manual/sections?version=1")
    r2 = client.get("/documents/ct200-manual/sections?version=2")
    assert r1.status_code == 200 and r2.status_code == 200
    # Safety Limits body differs between v1 and v2.
    sl_id = [s for s in r1.json() if s["heading_text"] == "Safety Limits"][0]["node_id"]
    v1 = client.get(f"/nodes/{sl_id}?version=1").json()
    v2 = client.get(f"/nodes/{sl_id}?version=2").json()
    assert "160 bpm" in v1["body_text"]
    assert "140 bpm" in v2["body_text"]
    assert v1["content_hash"] != v2["content_hash"]


def test_search_by_body_text(client):
    _ingest_real(client)
    r = client.get("/nodes/search?q=160 bpm")
    assert r.status_code == 200
    hits = r.json()
    assert any("Safety Limits" == h["heading_text"] for h in hits)


def test_diff_endpoint_reports_change(client):
    _ingest_real(client)
    client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual_v2.md")},
    )
    sl_id = [s for s in client.get("/documents/ct200-manual/sections?version=1").json() if s["heading_text"] == "Safety Limits"][0]["node_id"]
    d = client.get(f"/nodes/{sl_id}/diff?from=1&to=2").json()
    assert d["changed"] is True
    assert d["from_hash"] != d["to_hash"]
    assert "160" in (d["diff_summary"] or "") or "140" in (d["diff_summary"] or "")


def test_removed_node_reported_not_errored(client):
    """Cleaning exists in v1 but is removed in v2; GET at v2 must 404 with a
    'removed' message, and v1 still resolves."""
    _ingest_real(client)
    client.post(
        "/documents/ingest",
        json={"slug": "ct200-manual", "title": "CT-200", "file_path": str(DATA / "ct200_manual_v2.md")},
    )
    # find Cleaning node id via v1 search
    hits = client.get("/nodes/search?q=Cleaning&document_id=1&version=1").json()
    cleaning_id = [h for h in hits if h["heading_text"] == "Cleaning"][0]["node_id"]
    assert client.get(f"/nodes/{cleaning_id}?version=1").status_code == 200
    r2 = client.get(f"/nodes/{cleaning_id}?version=2")
    assert r2.status_code == 404
    assert "removed" in r2.json()["detail"]