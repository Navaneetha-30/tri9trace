# CT-200 QA Tracer

A small FastAPI service that turns the CardioTrack CT-200 markdown manual into a
versioned, browsable tree. It lets a user pick sections, drafts QA test-case ideas
from them with an LLM, and flags a previously generated test case as **stale**
when the source text it came from has changed.

This is a deliberately straightforward implementation. Design notes and the decision log are in `docs/APPROACH.md`.

## Stack

- FastAPI + Pydantic v2, SQLAlchemy 2.x + SQLite
- Groq for the LLM (`llama-3.3-70b-versatile`)
- Generations stored in a **local JSON file** by default; MongoDB if
  `MONGODB_URI` is set (optional)

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env          # set GROQ_API_KEY (MONGODB_URI optional)
uvicorn app.main:app --reload # http://127.0.0.1:8000/docs
pytest                        # tests, offline
```

Only `GROQ_API_KEY` is required (for `/generate`). Ingestion and browse work
with no external services.

## The v1 -> v2 re-ingestion flow

1. `POST /documents/ingest {slug, title, file_path}` -> persists version 1.
2. `GET /documents/{slug}/sections`, pick a node, `POST /selections {name, node_ids, version}` (version-pinned).
3. `POST /selections/{id}/generate` -> Groq drafts 3-5 test cases, stored with the exact content hash they came from.
4. Re-ingest v2 with the same slug (different `file_path`) -> version 2.
5. `GET /generations/{id}` -> `stale` flips to `true` if the source text changed.

Run it: `python scripts/demo_end_to_end.py` (or `bash scripts/demo_end_to_end.sh` against a running server).

### Sample run (real Groq)

```
ingested v1: 22 nodes
created selection id=1 pinned_version=1
generate: HTTP 200, parse_status=ok, 3 test cases
before re-ingest: stale=False
ingested v2: unchanged=12 changed=3 new=7
after re-ingest: stale=True stale_nodes=[21]
  diff_summary: node 21: +2 -2 lines; first change: 'The device enforces a hard heart-rate alarm threshold of 160 bpm. Patient'
```

Safety Limits changed from `160 bpm` / `5 kg` (v1) to `140 bpm` / `7 kg` (v2),
so a test case drafted against v1 is correctly flagged stale.

## API

```
POST   /documents/ingest
GET    /documents/{slug}/sections?version=latest|N
GET    /nodes/{node_id}?version=latest|N
GET    /nodes/search?q=&document_id=&version=
GET    /nodes/{node_id}/diff?from=&to=
POST   /selections                         {name, node_ids[], version}
GET    /selections/{id}
POST   /selections/{id}/generate           -> 502 if the LLM output can't be parsed
GET    /generations?selection_id=...       (each carries a staleness flag)
GET    /generations?node_id=...
GET    /generations/{id}                    (stale + diff summary if stale)
```

## Limitation

Staleness is a **binary content-hash check**. A wording fix and a changed safety threshold both flip the same `stale` flag — the system does not judge *what kind* of change it was. See `docs/APPROACH.md`.