"""End-to-end demo driver (FR7 final flow), runnable on Windows without curl.

Full flow against the real FastAPI app (TestClient) with the REAL Groq LLM and
the REAL generation store (Mongo if reachable, else the JSON fallback):

  ingest v1 -> browse sections -> create selection -> generate (real Groq)
  -> GET generation (fresh) -> ingest v2 -> GET generation (stale + diff)

Run:  python scripts/demo_end_to_end.py
Needs GROQ_API_KEY in .env (MONGODB_URI optional; falls back to JSON store).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.deps import get_llm, get_store
from app.db.session import SessionLocal, init_db
from app.ingest import ingest_file
from app.main import app

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    init_db()
    db = SessionLocal()

    print("== 1. Ingest v1 ==")
    r = ingest_file(db, "ct200-manual", "CT-200 Manual", str(DATA / "ct200_manual.md"))
    print(f"   ingested v1: {r['node_count']} nodes; warnings={r['warnings']}")

    # Use the real providers (Groq + Mongo/JSON store).
    app.dependency_overrides[get_llm] = _build_llm
    app.dependency_overrides[get_store] = _build_store
    client = TestClient(app)

    print("\n== 2. Browse top-level sections (v1) ==")
    sections = client.get("/documents/ct200-manual/sections?version=1").json()
    for s in sections:
        print(f"   - [{s['level']}] {s['heading_text']} (node {s['node_id']})")
    safety = [s for s in sections if s["heading_text"] == "Safety Limits"][0]

    print("\n== 3. Search 'bpm' ==")
    hits = client.get("/nodes/search?q=bpm&document_id=1&version=1").json()
    print(f"   {len(hits)} hit(s): {[h['heading_text'] for h in hits]}")

    print("\n== 4. Create selection pinned to v1 (Safety Limits) ==")
    sel = client.post("/selections", json={"name": "safety", "node_ids": [safety["node_id"]], "version": 1}).json()
    print(f"   selection id={sel['id']} pinned_version={sel['pinned_version']}")

    print("\n== 5. Generate test cases (real Groq) ==")
    gen = client.post(f"/selections/{sel['id']}/generate")
    print(f"   HTTP {gen.status_code}")
    g = gen.json()
    print(f"   parse_status={g['parse_status']} model={g['model']} cases={len(g['test_cases'])}")
    for tc in g["test_cases"]:
        print(f"     * {tc['title']}")

    gen_id = g["id"]

    print("\n== 6. Retrieve generation BEFORE re-ingest (should be fresh) ==")
    before = client.get(f"/generations/{gen_id}").json()
    print(f"   stale={before['stale']} stale_nodes={before['stale_nodes']}")

    print("\n== 7. Ingest v2 (Safety Limits: 160->140 bpm, 5->7 kg) ==")
    r2 = ingest_file(db, "ct200-manual", "CT-200 Manual", str(DATA / "ct200_manual_v2.md"))
    print(f"   ingested v2: unchanged={r2['unchanged']} changed={r2['changed']} new={r2['new']}")

    print("\n== 8. Retrieve the SAME generation AFTER re-ingest (stale + diff) ==")
    after = client.get(f"/generations/{gen_id}").json()
    print(f"   stale={after['stale']} stale_nodes={after['stale_nodes']}")
    print(f"   diff_summary: {after['diff_summary']}")

    print("\n== 9. List by selection (staleness inlined) ==")
    lst = client.get("/generations", params={"selection_id": sel["id"]}).json()
    print(f"   {len(lst)} generation(s); latest stale={lst[0]['stale']}")

    db.close()
    app.dependency_overrides.clear()
    print("\nDEMO OK")


def _build_llm():
    from app.llm.client import GroqProvider
    return GroqProvider()


def _build_store():
    from app.db.mongo import get_generation_store
    return get_generation_store()


if __name__ == "__main__":
    main()