# TRD — CardioTrack CT-200 QA Traceability & Test-Case Generation System

Companion to `01_PRD.md`. This is the technical contract execution prompts will build against.
Where a decision is genuinely data-dependent (parser irregularities, matching thresholds),
this doc states the *default* design and explicitly marks it "to be confirmed against real
document" — the execution prompts instruct Claude Code to update this file in place once it
inspects the real data, which is exactly the process the assignment wants documented.

---

## 1. Architecture Overview

```
                         ┌────────────────────────┐
  data/ct200_manual*.md  │   Ingestion Pipeline    │
  ───────────────────►   │  parser → tree builder  │
                         └───────────┬─────────────┘
                                     │ persists
                                     ▼
                         ┌────────────────────────┐        ┌─────────────────────┐
                         │   SQLite (SQLAlchemy)   │        │   MongoDB            │
                         │  documents/versions/    │        │  generations         │
                         │  nodes/selections        │        │  (LLM test-case sets)│
                         └───────────┬─────────────┘        └──────────┬──────────┘
                                     │                                  │
                                     ▼                                  ▼
                         ┌─────────────────────────────────────────────────────┐
                         │                 FastAPI application                  │
                         │  browse · selection · generation · staleness ·       │
                         │  retrieval routers                                   │
                         └───────────┬───────────────────────────────────────┬─┘
                                     │                                       │
                                     ▼                                       ▼
                         curl / Postman collection                 Groq LLM API (structured
                         (end-to-end demo script)                  output + retry wrapper)
```

## 2. Relational Data Model (SQLite via SQLAlchemy)

```
Document
  id (pk)
  slug            e.g. "ct200-manual"
  title
  created_at

DocumentVersion
  id (pk)
  document_id (fk -> Document.id)
  version_number      int, monotonically increasing per document
  source_filename      e.g. "ct200_manual_v2.md"
  ingested_at
  UNIQUE(document_id, version_number)

Node
  id (pk)                       -- STABLE LOGICAL ID, survives across versions
  document_id (fk -> Document.id)
  first_seen_version_id (fk -> DocumentVersion.id)
  logical_key                   -- matching-strategy fingerprint, see §5

NodeRevision
  id (pk)                       -- one row per node PER VERSION it appears in
  node_id (fk -> Node.id)
  document_version_id (fk -> DocumentVersion.id)
  parent_node_id (fk -> Node.id, nullable)   -- tree shape can itself change across versions
  heading_text
  level                           -- markdown heading depth, 1-6
  order_in_parent                 -- sibling ordering
  body_text                       -- raw body content owned by this heading (not children's)
  content_hash                    -- sha256(normalize(heading_text + body_text))
  is_changed_from_previous        -- bool, set at ingestion time vs. prior version's revision
  UNIQUE(node_id, document_version_id)

Selection
  id (pk)
  name
  created_at

SelectionNode
  id (pk)
  selection_id (fk -> Selection.id)
  node_id (fk -> Node.id)
  document_version_id (fk -> DocumentVersion.id)   -- THE version pin
  node_revision_id (fk -> NodeRevision.id)          -- exact content pin (redundant w/ above, explicit)
  UNIQUE(selection_id, node_id)
```

**Why `Node` (logical, cross-version) is separate from `NodeRevision` (per-version snapshot):**
this is the crux of FR2/FR6. A `Node.id` is a stable handle a human or a `Selection` can refer
to ("Section 4.2, Cuff Pressure Limits") across the document's whole lifetime. A
`NodeRevision` is the frozen text that existed under that heading at one specific version.
Staleness detection (FR6) is just: *does the `NodeRevision` a generation was pinned to equal
the current latest `NodeRevision` for that `Node`?*

## 3. Document Store (MongoDB) — `generations` collection

```jsonc
{
  "_id": ObjectId,
  "selection_id": 12,                 // fk-by-value into SQLite Selection.id
  "generated_at": "2026-07-17T...",
  "generation_index": 0,              // see §7 duplicate-submission policy
  "source_pins": [                    // exact content this generation was produced from
    {"node_id": 4, "document_version_id": 1, "node_revision_id": 4, "content_hash": "..."}
  ],
  "llm": {"provider": "groq", "model": "llama-3.3-70b-versatile", "prompt_version": "v1"},
  "raw_response": "...",              // stored for audit even if parsing failed
  "parse_status": "ok" | "malformed" | "retried_ok" | "failed",
  "retry_count": 0,
  "test_cases": [
    {
      "id": "tc-1",
      "title": "...",
      "steps": ["..."],
      "expected_result": "...",
      "source_node_ids": [4]
    }
  ]
}
```
Storing `raw_response` and `parse_status` is deliberate: a "correct staleness check nobody
can query for is not a finished feature" — the same logic applies to failed generations; they
should be inspectable, not swallowed.

## 4. Parsing Design (FR1)

**Default approach** (line-based, heading-driven, stack-based tree builder):
1. Walk the markdown line by line.
2. On an ATX heading line (`^#{1,6}\s`), pop the parent stack until top-of-stack level < this
   heading's level, attach as child, push.
3. All non-heading lines accumulate into the *current* node's `body_text` until the next
   heading.
4. Everything is buffered, never emitted, until the whole file parses without raising — if the
   parser cannot classify a line/block confidently, it raises `UnparseableBlockError` with the
   line number and content, rather than guessing. **A parser that silently drops content is a
   worse failure than one that stops.**

**Known irregularity classes to actively check for** (confirm against the real file in
execution prompt 2 — do not assume this list is exhaustive or all present):
- Duplicate heading text at the same or different levels (two `### Alarms` sections) →
  `Node.logical_key` cannot be heading text alone; must include the parent path, e.g.
  `"Safety Features > Alarms"`. If two duplicates share the same path too, key must include
  sibling order or fall back to a suffix (`Alarms (2)`) — and this fallback must be logged, not
  silent.
- Heading level skips (`#` directly to `###`) → tree builder must not assume levels are
  contiguous; it attaches at whatever the nearest valid ancestor level is and **flags** the
  skip in a parse-warnings log rather than pretending it's normal.
- Tables, code fences, or nested lists inside body text → treated as opaque body content
  (not parsed structurally), but must not be mistaken for headings by a naive `#`-prefix
  regex (e.g. a line inside a code fence that happens to start with `#`).
- Bold/italic lines that look like headings visually but aren't ATX headings → must NOT be
  promoted to nodes; parser matches only real ATX syntax.
- Front-matter or document title lines before the first real heading → captured as the
  document root's own preamble, not lost.

This section **must be rewritten with the actual findings** once the real document is
inspected (execution prompt 2, deliverable: an updated §4 here plus the approach doc's
"what I found / how I found it" section).

## 5. Version Matching Strategy (FR2)

**Default strategy: path-based logical key + content-hash fallback for confirmation.**

- `logical_key = normalize(heading_path)`, e.g. `"safety-features/alarms"`. Computed the same
  way at every ingestion.
- On re-ingest: for each new-version node, look up an existing `Node` with the same
  `logical_key` under the same `Document`.
  - **Match found** → reuse `Node.id`; create a new `NodeRevision` under it; compute
    `content_hash`; set `is_changed_from_previous = (new_hash != prior_revision.hash)`.
  - **No match found** (key doesn't exist in v1) → new `Node`, first revision, no "changed"
    flag (nothing to compare against — it's new).
  - **Old key no longer present in new version** → prior `Node` is not deleted (history must
    survive); it simply gets no `NodeRevision` for the new `DocumentVersion`. Browse API must
    report "removed in v_n" rather than erroring.
- **Why path-based over pure content-hash matching**: content hashing alone can't distinguish
  "this section's text changed" (the case we *want* to detect) from "this section moved/was
  renamed" (which would look like a delete+add and break the very traceability we're building).
  Path-based matching also fails, on purpose, in a case worth naming up front: **if a section
  is renamed AND its content changes in the same version bump, this strategy sees it as a
  deletion + a brand-new node**, losing the "same logical thing" link. This is a known,
  documented limitation, not a bug — fuzzy title matching would reduce this failure mode but
  introduces false-positive matches instead. This tradeoff must be stated explicitly in the
  approach doc's decision log.

## 6. API Surface (FastAPI)

```
POST   /documents/ingest                body: {slug, title, file_path}    → new DocumentVersion
GET    /documents/{slug}/sections       ?version=latest|N                  → top-level nodes
GET    /nodes/{node_id}                 ?version=latest|N                  → node + children + hash
GET    /nodes/search                    ?q=&version=                       → matching nodes
GET    /nodes/{node_id}/diff            ?from=&to=                         → changed bool + diff summary

POST   /selections                      body: {name, node_ids[], version}  → Selection (version-pinned)
GET    /selections/{selection_id}       → selection + resolved node text

POST   /selections/{selection_id}/generate     → triggers LLM generation, returns generation doc
GET    /generations?selection_id=       → list, each with staleness flag
GET    /generations?node_id=            → list, each with staleness flag
GET    /generations/{generation_id}     → single generation, staleness flag + diff if stale
```

## 7. LLM Generation Design (FR5)

- **Prompt contract**: system prompt instructs the model to return **only** a JSON array of
  3–5 objects matching `{title, steps: string[], expected_result, rationale}` — no prose, no
  markdown fences. Input includes the reconstructed selection text with explicit node
  boundaries so the model can produce plausible `source_node_ids` back-references.
- **Structured-output validation**: response is parsed via Pydantic (`TestCaseList` model).
  On `ValidationError` or JSON decode failure:
  1. Store `raw_response` + `parse_status="malformed"` regardless of outcome (never discard
     a failed response).
  2. Retry once with a corrective follow-up message quoting the validation error and asking
     for corrected JSON only (`parse_status="retried_ok"` if that succeeds).
  3. If retry also fails: `parse_status="failed"`, return HTTP 502 with the generation ID so
     the raw response is still inspectable — **do not fabricate test cases to paper over a
     bad response**, and do not return an empty 200 as if nothing happened.
- **Duplicate submission policy** (must be decided, defended): re-submitting the same
  selection **creates a new generation record** (`generation_index` incremented) rather than
  overwriting or silently deduping. Rationale: test-case generation is not idempotent by
  nature (LLM output varies), and silently returning a cached result would hide that a user
  asked twice; silently overwriting would destroy an audit trail in a QA context where audit
  trails are the point. The Browse/Retrieval API returns all generations for a
  selection/node, newest first, so a user isn't forced to dedupe manually. This is a real
  design choice with a real cost (storage grows with re-submissions) — call this out in the
  approach doc.

## 8. Staleness Detection (FR6)

For each `source_pins` entry in a stored generation:
```
current_revision = latest NodeRevision for source_pins[i].node_id at latest DocumentVersion
stale_i = (current_revision.content_hash != source_pins[i].content_hash)
generation.stale = any(stale_i)
generation.stale_nodes = [i for i where stale_i]
```
Diff summary for a stale node: unified-diff (`difflib`) between the pinned `body_text` and
current `body_text`, truncated/summarized (line-count of additions/removals + first changed
line) — not the full diff dumped raw, to keep the API response usable.

**Stated limitation (must appear in approach doc verbatim, this is the assignment's explicit
ask)**: this is a binary, content-hash-based flag. A whitespace or typo fix and a changed
safety threshold (e.g., cuff pressure limit) currently produce an *identical* signal: "stale."
The system does not currently weight *what kind* of change occurred. A stretch improvement
(explicitly deferred, named in "what I'd do differently") would be a semantic diff that
flags numeric/threshold changes as high-severity vs. prose-only changes as low-severity.

## 9. Testing Strategy

- Unit tests for the parser: ≥3 targeting real irregularities (FR1), plus a baseline
  "well-formed section" happy path.
- Unit tests for the version matcher: same-key-unchanged, same-key-changed, key-disappeared,
  key-appeared, duplicate-heading-disambiguation.
- Integration test: full ingest v1 → ingest v2 → assert exact set of `is_changed_from_previous`
  flags matches manual inspection of the two files.
- LLM layer: unit tests against **mocked** malformed/valid responses (do not depend on live
  Groq calls for CI-style tests); one manual/live smoke test documented in README.

## 10. Repo Layout

```
ct200-qa-tracer/
  app/
    main.py
    config.py                  # env vars: MONGODB_URI, GROQ_API_KEY
    db/
      models.py                 # SQLAlchemy models from §2
      session.py
      mongo.py                  # Mongo client + generations collection helpers
    parsing/
      parser.py                 # §4
      tree.py
    versioning/
      matcher.py                 # §5
    llm/
      client.py                  # Groq wrapper
      prompts.py
      schema.py                  # Pydantic TestCaseList
    api/
      documents.py
      nodes.py
      selections.py
      generations.py
  tests/
    test_parser.py
    test_matcher.py
    test_versioning_integration.py
    test_llm_validation.py
  data/
    ct200_manual.md
    ct200_manual_v2.md
  scripts/
    demo_end_to_end.sh          # curl-based full flow demo
  docs/
    APPROACH.md
  README.md
  .env.example
  requirements.txt
```
