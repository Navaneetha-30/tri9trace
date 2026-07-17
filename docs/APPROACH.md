# APPROACH — CT-200 QA Tracer

Companion to `docs/01_PRD.md` / `docs/02_TRD.md`. This documents what was
actually built and the reasoning behind it, including where the design
deliberately fails. The decision log at the end answers the three required
questions with reference to the real code and the real `data/ct200_manual*.md`.

## Data model summary

Relational (SQLite, SQLAlchemy) — see `app/db/models.py`:

- `Document` (slug, title) — a logical manual.
- `DocumentVersion` (document_id, version_number, source_filename) — one per
  re-ingest; `UNIQUE(document_id, version_number)`.
- `Node` (document_id, logical_key, heading_text, level) — a **stable logical
  id** for "this section" across versions; `UNIQUE(document_id, logical_key)`.
- `NodeRevision` (node_id, document_version_id, parent_node_id, heading_text,
  level, order_in_parent, body_text, content_hash, is_changed_from_previous) —
  a **frozen per-version snapshot**; `UNIQUE(node_id, document_version_id)`.
- `Selection` / `SelectionNode` — a named set pinning `(node_id,
  document_version_id, node_revision_id)` triples; `UNIQUE(selection_id, node_id)`.

Two-tier node identity is the crux: a `Node.id` is a stable handle a selection
refers to across the document's life; a `NodeRevision` is the frozen text that
existed at one version. Staleness (FR6) is just *does the NodeRevision a
generation was pinned to equal the latest NodeRevision for that Node?*.

Document store (MongoDB, `app/db/mongo.py`): a `generations` collection, one
doc per LLM generation, holding `selection_id`, `generation_index`,
`source_pins` (node_id, document_version_id, node_revision_id, content_hash,
heading_text, body_text), `llm` (provider/model/prompt_version), `raw_response`
+ `raw_attempts`, `parse_status`, `retry_count`, `validation_error`,
`test_cases`. `raw_response`/`parse_status` are stored for **every** attempt,
including failures, so a failed generation is inspectable rather than swallowed.

## Parsing decisions (per real irregularity in ct200_manual.md)

The parser (`app/parsing/parser.py`) is line-based, heading-driven,
stack-based, and **fails loudly** (`UnparseableBlockError`) instead of guessing.

What I found by reading the real file, and how each is handled:

- **Title/front-matter before the first heading** (`CardioTrack CT-200` /
  `Operator Manual` / `Revision 1.0 — Confidential`). These become the document
  root's `body_text` preamble — never lost. Tested.
- **Duplicate `### Power Requirements` under the same `## Installation`.** A
  path-based `logical_key` cannot be heading text alone: the duplicate is
  suffixed (`.../power-requirements (2)`) and a `duplicate_heading` warning is
  logged. Tested.
- **Heading level skip** (`## Device Overview` directly to `#### Components`,
  skipping `###`). The builder attaches to the nearest valid ancestor and
  flags a `level_skip` warning instead of crashing. Tested.
- **HTML `<div class="note">` block** inside `#### Components`, and a
  **markdown table** under `## Specifications`. Both are opaque `body_text`,
  never promoted to nodes; a `#` line inside a fenced code block is also not a
  heading. Tested.
- **Setext underline** (`===`): we support ATX only, so a `===` underline
  following body text raises (a real heading would otherwise be silently
  demoted to body). A `---` thematic break is left as body, not an error.

`content_hash = sha256(normalize(heading_text + "\n" + body_text))` where
`normalize` collapses whitespace and lowercases.

## Versioning strategy + failure modes (FR2)

Strategy (`app/versioning/matcher.py`): **path-based logical key + content-hash
confirmation**. `logical_key = slug(ancestor headings + this heading)`,
computed identically each ingest. On re-ingest:

- key exists → reuse `Node.id`, create a new `NodeRevision`, set
  `is_changed_from_previous = (new_hash != prior_hash)`.
- key absent → new `Node` (first_seen = this version), new revision, not
  "changed" (nothing to compare).
- old key absent in new version → the prior `Node` is **not deleted**; it gets
  no revision for the new version. Browse reports "removed" (404 with that
  word) rather than erroring.

Why path-based over pure content-hash: content-hash alone can't tell "this
section's text changed" (the thing we want to detect) from "this section moved
/ was renamed" (which would look like delete+add and break traceability).

**Known failure mode (deliberate, documented):** if a section is **renamed
AND its content changes in the same version bump**, this strategy sees a
deletion + a brand-new node, losing the "same logical thing" link. (Real
example: `## Troubleshooting` → `## Troubleshooting and FAQ` in v2; `####
Components` → `#### System Components`. Both are reported as new+deleted, not
"renamed".) Fuzzy title matching would reduce this but introduces
false-positive matches, which in a QA traceability context is worse than an
honest "new node" — so we don't do it.

## LLM prompt + retry strategy (FR5)

- **Prompt contract** (`app/llm/prompts.py`): the system prompt asks for ONLY a
  JSON object `{"test_cases":[...]}` with 3–5 items of
  `{title, steps[], expected_result, rationale, source_node_ids[]}`, with a
  concrete example so the model emits valid JSON (it has a strong tendency to
  write `"steps" = [...]` with an equals sign; the example + a retry reminder
  suppress that).
- **Structured-output validation** (`app/llm/schema.py`,
  `app/generation.py`): the response is run through `extract_json` (strips
  fences/prose, finds the first balanced `{...}`) then `TestCaseList`
  Pydantic validation. A single-string `steps` is coerced to a one-element
  list — **normalization, not fabrication** (the text is preserved verbatim).
- **Retry/failure policy**:
  1. On a `ValidationError`/`ValueError` (or a provider-level exception),
     store `raw_attempts[attempt]` and retry once with a corrective prompt
     quoting the validation error.
  2. If the retry parses → `parse_status="retried_ok"`.
  3. If the retry also fails → `parse_status="failed"`, return **HTTP 502**
     with the `generation_id` so the raw response is still inspectable. **We
     never fabricate test cases to paper over a bad response**, and we never
     return an empty 200 as if nothing happened.
- **Provider robustness**: Groq's JSON mode rejects borderline JSON with a
  `400 json_validate_failed` carrying a `failed_generation` field; we return
  that near-miss so the validation/retry path handles it (preserving it for
  audit) rather than crashing the request.
- **Duplicate-submission policy** (decided, defended): re-submitting the same
  selection **creates a new generation record** (`generation_index`
  incremented), never overwriting or silently deduping. LLM output is not
  idempotent, and overwriting would destroy a QA audit trail — which is the
  point of this domain. Cost: storage grows with re-submissions; the retrieval
  API returns all generations newest-first so a user isn't forced to dedupe.

## Staleness limitations (FR6) — the assignment's explicit ask

This is a **binary, content-hash-based flag**. A whitespace/typo fix and a
changed safety threshold (e.g. the cuff pressure / heart-rate alarm limit)
currently produce an **identical** signal: "stale". The system does **not**
currently weight *what kind* of change occurred. Confirmed against what was
built: the diff summary for `Safety Limits` says `+2 -2 lines; first change:
'The device enforces a hard heart-rate alarm threshold of 160 bpm...'` — a
human sees the threshold changed from 160 to 140, but the machine only says
"text changed, here is the line". A deferred improvement (semantic diff that
flags numeric/threshold changes as high-severity vs. prose-only as
low-severity) is named in "what I'd do differently".

## Decision log (three required questions)

**1. What's the part of this system most likely to silently give wrong results
without erroring, and how would you catch it?**

The **version matcher's path-based key**. If a section is renamed, the
matcher creates a new `Node` and silently orphan's the old one — no exception,
no warning, but the traceability link that selection staleness depends on is
broken (a selection pinned to the old node stays "fresh" forever because the
old node never gets a new revision to disagree with). How I'd catch it:
ingest should emit a `removed`/`new` pairing signal and, when a removed key
and a new key have very similar content, log a `possible_rename` warning so a
human reviews whether the link was lost. I currently report removed and new
honestly but do not attempt the pairing — that is the silent-wrong-results
risk. The offline integration test pins the *changed* set to manual inspection
so the happy path can't quietly drift.

**2. Where did you choose simplicity over correctness because of time, and what
would break first in production?**

The **binary hash-diff staleness**. A one-word wording fix and a changed
patient-safety threshold flip the same `stale` boolean. That is simple and
auditable, but in production the first thing that breaks is **reviewer
fatigue**: if every typo fix in the manual floods the staleness queue, reviewers
start ignoring stale flags, and the one flag that actually matters (the
threshold that moved from 160 to 140 bpm) gets missed — exactly the
patient-safety failure the system exists to prevent. The fix is a severity
layer (semantic / numeric-change detection), named below.

**3. Name one input to your parser/matcher/LLM call that you did NOT handle, and
what your system does when it sees it.**

**A setext heading (`text` followed by `===`) in the parser.** We support ATX
only, so when the parser sees an `===` underline that follows non-empty body
text it raises `UnparseableBlockError` (fail loudly) rather than silently
treating the would-be heading as body. The ingest endpoint surfaces this as a
`400` to the caller, who must re-save the section as an ATX (`#`) heading.
(Plain `---` is intentionally left as body/thematic-break, not an error, since
it is ambiguous and the real manuals contain table separators with dashes but
no setext underlines.)

## What I'd do differently with more time

- **Severity-weighted staleness.** Add a semantic-diff layer that classifies a
  change as high-severity (a number / threshold / unit changed — the
  patient-safety case) vs. low-severity (prose / whitespace only), instead of
  one boolean. This is the single highest-value change and is named in the PRD
  as a stretch goal.
- **Rename detection** in the matcher: pair a removed key with a new key of
  very similar content and offer a "this is a rename" link, fixing the silent
  traceability loss from question 1.
- **Idempotent ingest endpoint with auth.** Today ingest is a library-style
  `POST` with no auth; a production shape is an authenticated, idempotent
  `POST /documents/{id}/ingest` keyed on file content hash.
- **Embeddings for the matcher.** `difflib` character ratio misreads heavy
  paraphrase; token-overlap or embeddings would catch meaning-preserving
  rewrites that currently look like big text changes.
- **Mongo by default, not as a fallback** once the Atlas allowlist is in place;
  keep the JSON store only for offline tests.

## How reproducibility is verified

- `pytest` → 34 offline tests (parser irregularities, matcher edge cases, v1→v2
  integration asserting the exact changed set, browse, selection pinning,
  generation retry/failure, staleness, retrieval).
- `scripts/demo_end_to_end.py` → the real Groq LLM end-to-end (fresh → stale on
  the 160→140 bpm threshold change), captured in README.md.