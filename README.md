# CT-200 QA Tracer

QA traceability and test-case generation for the **CardioTrack CT-200**
operator manual. Parses a markdown manual into a versioned, browsable node
tree, lets a user pin a selection of sections, drafts QA test cases from that
selection with an LLM, and — the actual point — flags a previously generated
test case as **stale** when the source text it was drafted from has since
changed.

Built against `docs/01_PRD.md` and `docs/02_TRD.md` (see `docs/`). Full design
reasoning and the decision log live in `docs/APPROACH.md`.

## Stack

- **API**: FastAPI + Pydantic v2
- **Relational store**: SQLAlchemy 2.x + SQLite (documents, versions, nodes, selections)
- **Document store**: MongoDB Atlas for LLM generations, with a **local JSON-file
  fallback** behind the same interface when `MONGODB_URI` is unset or unreachable
- **LLM**: Groq (`llama-3.3-70b-versatile`) behind a swappable provider interface
- **Tests**: pytest (34 tests, offline — fake LLM + in-memory/JSON stores)

## Setup (< 10 min)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in GROQ_API_KEY (required for /generate)
                             # and MONGODB_URI (optional; JSON store used otherwise)
```

`GROQ_API_KEY` and `MONGODB_URI` are the only two env vars. **Ingestion and
browse routes work with zero external services configured** — only the
`/generate` route needs the Groq key, and only generation persistence uses
Mongo (falling back to a local JSON file if Mongo is not reachable, e.g. if
this machine's IP is not in your Atlas Network Access allowlist).

## Run

```bash
uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
```

## Run the tests

```bash
pytest                           # 34 tests, offline (no Groq/Mongo needed)
```

## The v1 -> v2 re-ingestion flow (assignment-required section)

This is the core traceability loop and the graded end-to-end path:

1. **Ingest v1**: `POST /documents/ingest {slug:"ct200-manual", title:"CT-200 Manual",
   file_path:"data/ct200_manual.md"}` → persists DocumentVersion 1 (22 nodes).
2. **Browse / select**: `GET /documents/ct200-manual/sections`, pick a node
   (e.g. "Safety Limits"), `POST /selections` pinning those `node_ids` to
   `version: 1`. The selection stores exact `(node, document_version,
   node_revision)` triples, so it is frozen to v1 content.
3. **Generate**: `POST /selections/{id}/generate` → Groq drafts 3-5 test cases,
   stored with `source_pins` (the exact node content hash they came from).
4. **Ingest v2**: re-`POST /documents/ingest` with
   `file_path:"data/ct200_manual_v2.md"` → DocumentVersion 2. The matcher reuses
   stable node ids where the path is unchanged and flags `is_changed_from_previous`
   by content hash. For the real files: 12 unchanged, 3 changed (Warnings,
   Recording, Safety Limits), 7 new.
5. **Check staleness**: `GET /generations/{gen_id}` recomputes staleness at
   retrieval time. A generation pinned to "Safety Limits" (v1: `160 bpm`,
   `5 kg`) becomes `stale=True` after v2 (`140 bpm`, `7 kg`), with a diff
   summary. The same call made on Introduction (byte-identical across v1/v2)
   stays `stale=False`.

### Run the demo

A Python driver (works on Windows without curl):

```bash
python scripts/demo_end_to_end.py
```

A curl version against a running server:

```bash
bash scripts/demo_end_to_end.sh     # after `uvicorn app.main:app` is up
```

### Demo run (real Groq, captured from this machine)

```
== 1. Ingest v1 ==
   ingested v1: 22 nodes; warnings=["heading level 4 attached under level 2 (skip of 1); attached to 'Device Overview'", "duplicate logical key 'cardiotrack-ct-200-operator-manual/installation/power-requirements'; renamed to 'cardiotrack-ct-200-operator-manual/installation/power-requirements (2)'"]

== 2. Browse top-level sections (v1) ==
   - [2] Introduction (node 2)
   - [2] Device Overview (node 5)
   - [2] Installation (node 8)
   - [2] Operating Instructions (node 11)
   - [2] Specifications (node 15)
   - [2] Maintenance (node 16)
   - [2] Troubleshooting (node 19)
   - [2] FAQ (node 20)
   - [2] Safety Limits (node 21)
   - [2] Revision History (node 22)

== 3. Search 'bpm' ==
   3 hit(s): ['Alarms', 'Safety Limits', 'Specifications']

== 4. Create selection pinned to v1 (Safety Limits) ==
   selection id=1 pinned_version=1

== 5. Generate test cases (real Groq) ==
   [store] MongoDB unreachable (ServerSelectionTimeoutError); falling back to JSON store. Add this machine's IP to the Atlas Network Access allowlist to use Mongo.
   HTTP 200
   parse_status=ok model=llama-3.3-70b-versatile cases=3
     * Heart Rate Threshold
     * Patient Load Limit
     * Temperature Range

== 6. Retrieve generation BEFORE re-ingest (should be fresh) ==
   stale=False stale_nodes=[]

== 7. Ingest v2 (Safety Limits: 160->140 bpm, 5->7 kg) ==
   ingested v2: unchanged=12 changed=3 new=7

== 8. Retrieve the SAME generation AFTER re-ingest (stale + diff) ==
   stale=True stale_nodes=[21]
   diff_summary: node 21: +2 -2 lines; first change: 'The device enforces a hard heart-rate alarm threshold of 160 bpm. Patient'

== 9. List by selection (staleness inlined) ==
   1 generation(s); latest stale=True
```

(The `[store]` line above is honest: this machine's IP is not in the Atlas
allowlist, so the generation store auto-fell back to the JSON file — the flow
is otherwise identical. Adding the IP to Atlas Network Access switches it to
Mongo with no code change.)

## API surface

```
POST   /documents/ingest                         body {slug, title, file_path}
GET    /documents/{slug}/sections?version=latest|N
GET    /documents/{slug}/versions
GET    /nodes/{node_id}?version=latest|N         node + children + content_hash
GET    /nodes/search?q=&document_id=&version=
GET    /nodes/{node_id}/diff?from=&to=            changed bool + diff summary

POST   /selections                               {name, node_ids[], version} (version-pinned)
GET    /selections/{selection_id}                resolved pinned node text
POST   /selections/{selection_id}/generate       LLM -> 3-5 test cases (502 if it can't)
GET    /generations?selection_id=...             list, each with staleness flag
GET    /generations?node_id=...
GET    /generations/{generation_id}              single, stale + diff summary if stale
```

## Project layout

```
app/
  main.py, config.py, deps.py, generation.py, queries.py, schemas.py
  db/        models.py, session.py, mongo.py
  parsing/   parser.py, tree.py
  versioning/ matcher.py, staleness.py
  llm/       client.py, prompts.py, schema.py
  api/       documents.py, nodes.py, selections.py, generations.py
tests/       (parser, matcher, versioning integration, browse, selection,
              generation, staleness, retrieval)
data/        ct200_manual.md, ct200_manual_v2.md
scripts/     demo_end_to_end.py, demo_end_to_end.sh
docs/        01_PRD.md, 02_TRD.md, 03_EXECUTION_PROMPTS.md, APPROACH.md
```