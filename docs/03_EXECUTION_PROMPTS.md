# Execution Prompts — Claude Code / Opus 4.8

How to use this file: run these **one at a time**, in order, in Claude Code (Opus 4.8), inside
an empty project folder. After each prompt finishes, actually read the diff/output before
moving to the next one — several prompts depend on decisions the previous one made (real
irregularities found, real matching edge cases hit). Each prompt ends by telling Claude Code
to commit. Don't batch commits across prompts; that defeats the "real incremental history"
requirement you're graded on.

Before Prompt 1: copy `01_PRD.md` and `02_TRD.md` into `docs/` in your new repo folder, and
place the real `ct200_manual.md` and `ct200_manual_v2.md` in `data/`. Claude Code should read
`docs/01_PRD.md` and `docs/02_TRD.md` at the start of every prompt below — they're the spec.

---

## Prompt 0 — Preflight (run this first, not part of the numbered 9, but do not skip)

```
Before writing any code: list the contents of ./data/. If ct200_manual.md or
ct200_manual_v2.md are missing, stop and tell me — do not fabricate placeholder medical
device content to fill the gap. If they exist, open and read ct200_manual.md fully (not just
the first N lines) and give me a short summary of its structure: heading levels used, roughly
how many sections, and anything that looks structurally irregular to you on a first read
(duplicate headings, inconsistent heading depth, tables, code blocks, anything else). Don't
write a parser yet — I just want confirmation you've actually read it before we design
against it. Also confirm ct200_manual_v2.md exists and give me the same summary for it.
```

---

## Prompt 1 — Scaffolding

```
Read docs/01_PRD.md and docs/02_TRD.md fully. We're building the system they describe.

Set up the project skeleton exactly per the TRD §10 repo layout:
- Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, pytest, pymongo, groq (or an HTTP
  client if the groq SDK is unavailable), python-dotenv.
- requirements.txt with pinned versions.
- app/config.py reading MONGODB_URI and GROQ_API_KEY from environment (via .env locally),
  with a clear error message (not a silent None) if either is missing at startup for routes
  that need them. Ingestion/browse routes must work with zero external services configured;
  only the /generate route needs both keys.
- app/db/session.py: SQLAlchemy engine + session factory against SQLite file
  ./ct200_qa.db (gitignored).
- app/db/mongo.py: a thin wrapper around a MongoDB client + the `generations` collection,
  with a fallback: if MONGODB_URI is unset, fall back to a local JSON-file-backed store
  behind the SAME interface (so the rest of the app never knows which backend is active).
  Document this fallback explicitly in a comment and in the README later.
- app/main.py: FastAPI app, health check route (GET /health), routers included but empty
  for now.
- .env.example listing MONGODB_URI and GROQ_API_KEY with placeholder values and a one-line
  comment each.
- .gitignore (venv, __pycache__, .env, *.db, .pytest_cache).
- Initialize git if not already, first commit: "chore: project scaffolding".

Then: actually run the app (uvicorn) and hit /health to confirm it boots before you commit.
Report what you did and commit.
```

---

## Prompt 2 — Ingestion & Structuring (FR1)

```
Read docs/02_TRD.md §4 (Parsing Design). You already read ct200_manual.md in the preflight
step and reported its structure back to me — use that, and re-inspect the file as closely as
needed while building.

Implement app/parsing/parser.py and app/parsing/tree.py per TRD §4: a line-based, heading-
driven, stack-based tree builder that:
- Never silently drops or mis-parents a line of content.
- Raises a clear, specific error (with line number + content snippet) on anything it can't
  confidently classify, rather than guessing.
- Correctly handles every structural irregularity actually present in ct200_manual.md —
  not a hypothetical list. If something in TRD §4's "known irregularity classes" doesn't
  actually occur in the real file, don't over-build for it; if something occurs that ISN'T
  in that list, handle it and tell me.
- Produces, for each node: heading text, level, body_text (only this node's own body, not
  children's), parent/child links, and content_hash = sha256 of a normalized
  (whitespace-collapsed) form of heading_text + body_text.

Implement app/db/models.py per TRD §2 (Document, DocumentVersion, Node, NodeRevision,
Selection, SelectionNode) and app/db/session.py migrations/create_all.

Implement a POST /documents/ingest endpoint (app/api/documents.py) that takes a slug, title,
and file_path, parses the file, and persists it as DocumentVersion 1 with its full node tree.

Write tests/test_parser.py with at least 3 tests, each targeting a SPECIFIC irregularity you
found in the real ct200_manual.md (name the irregularity in the test name/docstring, e.g.
test_duplicate_heading_produces_distinct_node_ids). Also write one baseline "well-formed
section parses correctly" test.

Now, critically: update docs/02_TRD.md §4 to reflect what you actually found (replace the
placeholder/default text with the real findings), and start docs/APPROACH.md with a section
"What I found in the document and how I found it" — be specific: did you find it by reading
the raw file, by writing a quick script to grep for heading patterns, by a test failing, by
tree output looking wrong? Say which.

Run the tests, confirm they pass, ingest the real file via the endpoint and sanity-check the
resulting tree (print it or query the DB) before committing.

Commit as one logical unit: "feat: markdown parser + tree persistence + ingestion endpoint
(FR1)". If you had to make more than one meaningfully separate change, use more than one
commit.
```

---

## Prompt 3 — Document Versioning (FR2)

```
Read docs/02_TRD.md §5 (Version Matching Strategy) and the current state of
docs/APPROACH.md.

Implement app/versioning/matcher.py per TRD §5: path-based logical_key matching with the
documented fallback for duplicate paths, plus content-hash comparison to set
is_changed_from_previous on each new NodeRevision.

Extend POST /documents/ingest so that ingesting a file for a slug that already has a
DocumentVersion creates DocumentVersion N+1 using the matcher — not a fresh document. Verify
version 1 is untouched (query it after ingesting v2 and confirm its node revisions are
unchanged).

Ingest data/ct200_manual_v2.md as version 2 now. Compare what got flagged as changed against
your own manual reading of a diff between the two files (use `diff` or read them side by
side). If the matcher's flags don't match your manual read, that's a bug or a real limitation
— figure out which, and either fix it or document it as a known limitation in
docs/APPROACH.md's "version-matching strategy and its known failure modes" section (TRD §5
already names one probable failure mode — confirm whether it actually occurs in this
document, or find a different one that does).

Write tests/test_matcher.py covering: same-key-unchanged, same-key-changed, key-disappeared-
in-new-version, key-appeared-in-new-version, and the duplicate-heading disambiguation case
from Prompt 2 if that irregularity is real in this document. Write
tests/test_versioning_integration.py that ingests both real files and asserts the actual set
of changed node paths matches what you determined by manual inspection (hardcode that
expected set based on your real findings, don't guess).

Update docs/APPROACH.md's versioning section with your justification and known failure
modes. Run tests, confirm pass, commit: "feat: document re-ingestion + version matching
(FR2)".
```

---

## Prompt 4 — Browse API (FR3)

```
Read docs/02_TRD.md §6 for the API surface.

Implement app/api/nodes.py and extend app/api/documents.py:
- GET /documents/{slug}/sections?version=latest|N — top-level nodes only, correct
  children/parent resolution for the requested version.
- GET /nodes/{node_id}?version=latest|N — node + its children (for that version) + full
  body text + content_hash. Handle the case where the node doesn't exist in the requested
  version (was added later, or removed) with a clear 404 vs. "existed but not in this
  version" distinction — don't just 500.
- GET /nodes/search?q=&version= — case-insensitive substring match across heading_text and
  body_text for the given version; return node id, heading, path, and a short snippet.
- GET /nodes/{node_id}/diff?from=&to= — return {changed: bool, from_hash, to_hash,
  diff_summary} using difflib per TRD §8's diff-summary approach (line counts + first
  changed line, not a raw full diff dump).

Add tests for each endpoint, including the version-not-found and node-removed-in-version
edge cases (you now know from Prompt 3 whether any real nodes were actually added/removed
between v1 and v2 — if none were, write the test against a synthetic case and say so in a
comment, don't skip the edge case just because the real data didn't happen to exercise it).

Update scripts/demo_end_to_end.sh (create it if it doesn't exist yet) with curl examples for
every endpoint built so far.

Run tests, commit: "feat: browse API — list/get/search/diff (FR3)".
```

---

## Prompt 5 — Selection API (FR4)

```
Read docs/02_TRD.md §2 (SelectionNode table) and §6.

Implement app/api/selections.py:
- POST /selections — body: {name, node_ids: [...], version}. For each node_id, resolve the
  NodeRevision that exists at the given version and persist a SelectionNode pinning
  (node_id, document_version_id, node_revision_id). If any node_id doesn't exist at that
  version, fail the whole request with a clear error listing which ones — a partial
  selection is worse than a rejected one.
- GET /selections/{selection_id} — return the selection's metadata plus, for each pinned
  node, the ORIGINAL pinned text (not the current/latest text) reconstructed from
  node_revision_id directly, regardless of whether the document has since been re-ingested.

Write a test that: creates a selection against version 1, then ingests version 2 (which may
or may not change that node's text depending on what you found in Prompt 3), then re-fetches
the selection and asserts it STILL returns the v1 text verbatim. This is the core guarantee
of FR4 — the test must actually exercise re-ingestion happening after selection creation, not
just check the pin exists.

Update scripts/demo_end_to_end.sh with the selection flow. Run tests, commit:
"feat: version-pinned selection API (FR4)".
```

---

## Prompt 6 — LLM Generation API (FR5)

```
Read docs/02_TRD.md §3 (generations collection) and §7 (LLM Generation Design) carefully —
this is the part of the assignment that explicitly penalizes skipping structured-output
validation and "it usually works" thinking.

Implement:
- app/llm/prompts.py — the system + user prompt per TRD §7. Make the prompt instruct JSON-
  only output, 3-5 test cases, each with title/steps/expected_result/rationale/
  source_node_ids referencing the input node IDs you provide it.
- app/llm/schema.py — Pydantic model(s) for validating the response (TestCase, TestCaseList).
- app/llm/client.py — wrapper around the Groq API (read GROQ_API_KEY from config; fail with
  a clear message if unset). Implement the retry contract from TRD §7 exactly: on invalid
  JSON/schema mismatch, retry once with a corrective message quoting the actual validation
  error, then give up and mark parse_status="failed" — never fabricate test cases to cover a
  bad response, never silently return an empty success.
- app/db/mongo.py generations helpers: insert_generation, get_by_selection, get_by_node.
- app/api/generations.py — POST /selections/{selection_id}/generate: reconstructs pinned
  text from the selection (using selections logic from Prompt 5), calls the LLM, validates,
  stores per TRD §3 schema (including raw_response and parse_status ALWAYS, even on
  failure), returns the stored generation or a 502 with the generation id if it truly
  failed after retry.
- Implement the duplicate-submission policy from TRD §7 exactly: re-submitting the same
  selection creates a new generation with an incremented generation_index; it does not
  overwrite or dedupe.

Write tests/test_llm_validation.py using MOCKED LLM responses (do not call the real API in
automated tests): one well-formed response, one malformed-then-corrected-on-retry response,
one malformed-on-both-attempts response — assert parse_status and stored raw_response are
correct in all three cases.

Then do ONE real live call against Groq with a real selection from the real document (you'll
need GROQ_API_KEY set locally for this one manual step) and paste the actual response you got
into docs/APPROACH.md as evidence, along with whether it validated cleanly first try. If it
didn't validate cleanly, that's useful signal — say so honestly rather than only showing a
clean run.

Update docs/APPROACH.md with the LLM prompt design rationale and the retry/duplicate-
submission decisions (TRD §7 already has the reasoning — restate it in your own words and
add anything you learned from the real call). Update scripts/demo_end_to_end.sh. Run mocked
tests, confirm pass, commit: "feat: LLM-powered test case generation with structured-output
validation and retry (FR5)".
```

---

## Prompt 7 — Staleness / Impact Detection (FR6)

```
Read docs/02_TRD.md §8.

Implement the staleness computation described there: for a stored generation, compare each
source_pins[i].content_hash against the CURRENT latest NodeRevision content_hash for that
node_id. Expose it as a reusable function (app/versioning/staleness.py or similar), not
inlined into a route handler, since Prompt 8 needs to call it too.

Produce a diff_summary for stale nodes using difflib, following TRD §8's guidance (summarized,
not a raw dump): counts of added/removed lines plus the first changed line.

Write a test that: generates test cases from a selection pinned to v1, then ingests v2, then
recomputes staleness and asserts the correct stale/not-stale result based on whether that
specific node's text actually changed between your two real files (you know this from
Prompt 3's findings — use the real answer, don't assume).

In docs/APPROACH.md, add the "staleness limitations" paragraph the assignment explicitly asks
for: state plainly whether your current implementation would treat a one-word wording fix
and a changed numeric safety threshold identically (per TRD §8, it does — confirm this is
still true of what you built, or note if you improved on it and how).

Commit: "feat: staleness detection (FR6)".
```

---

## Prompt 8 — Retrieval API (FR7) + Final Polish

```
Read docs/02_TRD.md §6 and §8.

Implement:
- GET /generations?selection_id=... and GET /generations?node_id=... — list generations,
  each annotated with the staleness result from Prompt 7 (stale: bool, stale_nodes: [...]).
- GET /generations/{generation_id} — single generation with staleness + diff_summary for any
  stale source nodes.

Finish scripts/demo_end_to_end.sh so it runs the ENTIRE flow in order end-to-end against a
running server: ingest v1 → browse sections → search → create selection → generate test
cases → ingest v2 → re-fetch the same generation via retrieval API and show the staleness
flag flip (or confirm it correctly stays false, whichever is true for the real data) → fetch
the diff summary. Run this script for real against a locally running server and paste its
actual output into README.md as a "Demo run" section — not a hypothetical example.

Now write docs/APPROACH.md's remaining required sections if not already present from earlier
prompts:
- Full data model summary (can reference docs/02_TRD.md §2, don't duplicate verbatim).
- Decision log — answer all 3 required questions from the assignment directly and
  specifically, based on what you actually built, not generically:
  1. What's the part of this system most likely to silently give wrong results without
     erroring, and how would you catch it?
  2. Where did you choose simplicity over correctness because of time, and what would break
     first in production?
  3. Name one input to your parser/matcher/LLM call that you did NOT handle, and what your
     system does when it sees it.
- "What I'd do differently with more time."

Write README.md: setup (venv, requirements.txt, .env from .env.example), how to run
(uvicorn command), how to run tests, and an explicit step-by-step for triggering the v1→v2
re-ingestion flow specifically (the assignment calls this out as a required README section).

Do a final pass: run the full test suite, run the demo script one more time clean, check
`git log --oneline` actually reads as a believable incremental history (if any prompt above
got squashed into one giant commit, split it retroactively via interactive rebase now, before
this becomes the final state).

Final commit: "docs: README, approach doc, decision log, end-to-end demo output". Then
confirm with me before you do anything with git remotes / pushing — I'll want to review
docs/APPROACH.md myself first.
```

---

## Notes on using these prompts

- **Don't skip Prompt 0.** If Claude Code fabricates irregularities instead of finding real
  ones, the entire "process" story in the approach doc — which the assignment explicitly says
  matters more than clean code — becomes fake, and it reads as fake to a reviewer who opens
  the real file.
- If Claude Code's output at any step disagrees with the TRD (e.g., a genuinely better
  matching strategy occurs to it while building), that's fine — the instruction in every
  prompt to update the relevant TRD/APPROACH section in place means the docs stay truthful
  to what was actually built, which is what gets graded.
- After Prompt 8, zip the repo folder (excluding `.venv`, `__pycache__`, `*.db`) or push it to
  a real GitHub repo — the assignment wants an actual GitHub repo with real history, not just
  a zip, so treat the zip as your personal backup and push to GitHub as the actual deliverable.
