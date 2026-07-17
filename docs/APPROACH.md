# APPROACH — CT-200 QA Tracer

Notes on what was built and why, with the decision log at the end. Built
against `docs/01_PRD.md` / `docs/02_TRD.md`.

## Data model

Relational (SQLite): `Document` -> `DocumentVersion` (one per re-ingest) ->
`Node` (a stable logical id per section) -> `NodeRevision` (a frozen per-version
snapshot: heading, body, content_hash, is_changed_from_previous).
`Selection` -> `SelectionNode` pins `(node_id, document_version_id,
node_revision_id)` so a selection is frozen to exact version content.

Generations (LLM output) are stored as documents in the generation store
(MongoDB if `MONGODB_URI` is set, else a local JSON file), one per generation,
holding the source pins, prompt/model version, raw response, parse status, and
test cases. Failed generations are kept too (never swallowed).

## Parsing

Line-based, heading-driven, stack-based (`app/parsing/parser.py`). It fails
loudly (`UnparseableBlockError`) instead of guessing. Real irregularities
handled in `data/ct200_manual.md`:

- Title lines before the first heading -> captured as the root preamble.
- Two `### Power Requirements` under one parent -> the second logical key is
  suffixed `(2)` and a warning is logged.
- `## Device Overview` -> `#### Components` (level skip) -> attaches to the
  nearest ancestor and flags a warning instead of crashing.
- HTML `<div>` and markdown tables -> opaque body, never headings.
- A setext `===` underline -> raises (we support ATX only).

`content_hash = sha256(normalize(heading_text + body_text))`.

## Versioning (FR2)

Path-based logical key + content hash (`app/versioning/matcher.py`). Same key
on re-ingest reuses the `Node` id and adds a new `NodeRevision`;
`is_changed_from_previous` is set by hash diff. A key that disappears keeps
its history (no new revision; browse reports "removed"). A key that appears is
a new node.

Failure mode: a section renamed *and* changed in one bump is seen as a
delete + a new node, losing the link. Fuzzy matching would add false positives,
so it is not used.

## LLM generation (FR5)

The model is asked for a JSON object of 3-5 test cases. The response is
validated with Pydantic. On a validation failure it retries once with the
error fed back; a second failure is stored and returned as HTTP 502 with the
generation id — never fabricated into a fake success. A single-string `steps`
is coerced to a one-element list (normalization, not fabrication). Re-submitting
the same selection creates a new generation record (never overwritten), to
preserve a QA audit trail.

## Staleness (FR6) — limitation

Binary content-hash check. For each source pin, compare its stored hash to the
node's revision in the current latest version; a mismatch (or a removed node)
means `stale=True`, with a summarized difflib diff. A typo fix and a changed
safety threshold produce the *same* signal. The system does not classify the
*kind* of change. That is a known, deliberate simplification.

## Decision log

**1. What is most likely to silently give wrong results without erroring, and
how would you catch it?**
The path-based matcher. A renamed section becomes a new node and the old one
is orphaned — no error, but the selection pinned to the old node stays "fresh"
forever because the old node never gets a new revision to disagree with. I'd
catch it by pairing each removed key with a new key of very similar content
and logging a `possible_rename` warning for a human to review. Today it
reports removed/new honestly but does not attempt the pairing.

**2. Where did you choose simplicity over correctness, and what breaks first in
production?**
The binary hash-diff staleness. It is simple and auditable, but in production
reviewer fatigue breaks first: every typo fix floods the stale queue, people
stop looking, and the one flag that matters (a threshold that moved) is missed.
The fix is a severity layer that weights numeric/threshold changes higher than
prose-only changes.

**3. Name one input you did NOT handle, and what happens when it appears.**
A setext heading (`text` + `===`) in the parser. We support ATX only, so it
raises `UnparseableBlockError` (fail loudly) rather than silently demoting the
would-be heading to body. The ingest endpoint returns a 400 and the caller
re-saves the section as an ATX (`#`) heading. (A `---` line is left as body,
since it is ambiguous and not a heading underline.)

## What I'd do differently

- A severity-weighted staleness layer (numeric/threshold changes vs. prose).
- Rename detection in the matcher (pair removed + new similar keys).
- Authenticated, idempotent ingest endpoint.
- Use MongoDB by default once network access is set up; keep the JSON store for
  offline tests only.