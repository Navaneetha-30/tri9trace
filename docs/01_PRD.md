# PRD — CardioTrack CT-200 QA Traceability & Test-Case Generation System

**Project codename:** `ct200-qa-tracer`
**Author:** (you)
**Source brief:** Tri9T AI — AI Engineering Internship Assignment
**Status:** Draft v1

---

## 1. Problem Statement

Regulated medical-device documentation (device manuals, requirement specs) changes over
time. QA teams write test cases against specific sections of that documentation. When the
documentation changes, nobody automatically knows which previously-written test cases still
reflect reality and which are now **stale** — silently wrong. Missed staleness in this domain
can mean a test suite gives false confidence, and in the worst case, a missed patient-safety
bug ships.

This system takes a markdown technical manual for a fictional blood-pressure monitor
(CT-200), turns it into a structured, versioned, browsable tree, lets a user select sections of
it, generates QA test-case ideas from that selection via an LLM, and — critically — tells the
user at retrieval time whether the text a test case was generated from has since changed.

## 2. Goals

1. Parse an irregular real-world markdown document into a correct hierarchical tree — not a
   tree that merely *looks* correct.
2. Version that tree across re-ingestions without destroying history or duplicating unchanged
   content.
3. Let a user browse, search, and diff across versions.
4. Let a user select a set of nodes and pin that selection to exact node+version content.
5. Generate QA test-case ideas from a selection via an LLM, with real handling of malformed
   LLM output (not just a happy path).
6. Detect and surface staleness of previously generated test cases when the source document
   changes — and be honest about the approach's blind spots (e.g., a typo fix vs. a changed
   safety threshold currently look the same to a hash-diff).
7. Ship with real incremental git history, a README, an approach doc, and a decision log that
   demonstrates judgment, not just working code.

## 3. Non-Goals (explicitly out of scope per assignment)

- Auth / user accounts.
- A fully generic markdown parser for arbitrary documents (this parser only needs to be
  correct for CT-200-style docs and *fail loudly*, not silently, on things it can't handle).
- Auto-regeneration of stale test cases (we only **detect and report** staleness).
- Any frontend/UI. A curl/Postman script demonstrating the full flow is the deliverable.

## 4. Users / Personas

- **QA Engineer** — browses the manual tree, selects sections, requests test-case ideas,
  later checks whether prior test cases are still valid after a doc update.
- **Reviewer / hiring panel** (in this assignment's context) — reads the approach doc and
  decision log, inspects commit history, and will ask you to defend specific design choices
  live.

## 5. Functional Requirements

Mapped directly to the assignment's 7 build items. Each maps 1:1 to an execution-prompt
stage later in this package.

### FR1 — Ingestion & Structuring
- Parse `data/ct200_manual.md` into a tree of nodes: heading text, level, body text,
  parent/child links, content hash (for staleness detection later).
- Persist the tree (SQLite via SQLAlchemy).
- Must correctly handle every structural irregularity actually present in the source file
  (duplicate headings, inconsistent heading depth jumps, tables, lists that look like
  headings, code blocks, etc. — **the real list is determined by inspecting the real file**,
  not assumed in advance).
- Parser must fail loudly (raise/flag) on anything it doesn't recognize, never silently drop
  or mis-parent content.
- ≥3 unit tests, each targeting a specific irregularity found in the real document.

### FR2 — Document Versioning
- Re-ingest `data/ct200_manual_v2.md` as version 2 of the same logical document, without
  destroying version 1.
- Nodes unchanged in substance between v1 and v2 must be recognized as the same logical
  node (not duplicated).
- Nodes whose body changed must be flagged as changed.
- Matching strategy is an engineering choice (path-based / hash-based / fuzzy title) —
  justified in the approach doc, including where the strategy breaks.

### FR3 — Browse API
- List top-level sections, with a `version` query param (default: latest).
- Get a node by ID: children, full text, content hash.
- Search/filter nodes by heading or body text.
- Given a node ID, report whether it changed across versions, with a lightweight diff
  summary.

### FR4 — Selection API
- Submit a named set of node IDs as a "selection."
- Selections are **version-pinned**: they store node+version pairs, so a later re-ingestion
  never silently changes what an old selection refers to.

### FR5 — LLM-Powered Generation API
- Given a selection, reconstruct its text, send to an LLM with a designed prompt, generate
  3–5 QA test-case ideas.
- Validate structured output; define and implement a concrete retry/failure policy for
  malformed/incomplete LLM responses.
- Store generated output linked to (a) the selection and (b) the exact node content
  (hash-pinned) it was generated from, so it remains interpretable after re-versioning.
- Define and implement a policy for duplicate submission of the same selection
  (e.g., idempotent return of prior generation vs. new generation vs. versioned generations)
  and be able to defend it.

### FR6 — Staleness / Impact Detection
- At retrieval time, tell the user whether a previously generated test case still reflects the
  *current* document text for the node(s) it was generated from.
- Be explicit in the approach doc about the method's limits (e.g., any body-text change flips
  a boolean "stale" flag regardless of whether it's a typo fix or a changed safety threshold).

### FR7 — Retrieval API
- Fetch previously generated test cases by selection ID or by node ID.
- Every generation returned must carry a staleness flag (from FR6) — a correct staleness
  check that isn't queryable here doesn't count as done.

## 6. Non-Functional Requirements

- **Correctness over cleverness**: a parser/matcher that fails visibly is preferred over one
  that silently produces a plausible-looking wrong tree.
- **Traceability**: every generated test case must be traceable back to exact node content,
  not just a node ID (which can point to different text after re-versioning).
- **Reproducibility**: README must let a reviewer clone, set two env vars (`GROQ_API_KEY`,
  `MONGODB_URI`), and run the full ingest → select → generate → re-ingest → check-staleness
  flow.
- **Git hygiene**: commit history must show real incremental development (this is explicitly
  graded), not one squashed commit.

## 7. Tech Stack

Per assignment's expected stack (deviations must be justified in approach doc):
- **API**: FastAPI + Pydantic
- **Relational store** (tree, versions, selections): SQLAlchemy + SQLite
- **Document store** (LLM generations): MongoDB (Atlas free tier or local) — or a
  well-justified JSON store if Mongo access is unavailable
- **LLM provider**: Groq (free tier) — swappable via an abstraction layer
- **VCS**: Git, real incremental commits

## 8. Success Criteria / Definition of Done

- [ ] Full flow (ingest v1 → browse → select → generate → ingest v2 → check staleness →
      retrieve) runs end-to-end via a documented script/collection.
- [ ] ≥3 parser unit tests targeting real, discovered irregularities, all passing.
- [ ] Approach doc contains: data model, parsing decisions per irregularity, versioning
      strategy + failure modes, LLM prompt + retry strategy, decision log (3 required
      questions answered with real reasoning).
- [ ] README lets a fresh clone run in <10 minutes given API keys.
- [ ] Commit history shows incremental, logically separated work matching the 7 FRs.
- [ ] Author can defend every design choice live and name a weak spot unprompted.

## 9. Risks / Open Questions

- The actual structural irregularities in `ct200_manual.md` are unknown until inspected —
  all irregularity-specific requirements in FR1 are placeholders until that inspection happens
  (this is by design; see execution prompt 2).
- Groq structured-output reliability is unproven for this exact prompt until tested — retry
  policy must be validated against real malformed responses, not assumed.
- Mongo Atlas free-tier network access from the dev environment must be confirmed early
  (execution prompt 1) to avoid late surprises.
