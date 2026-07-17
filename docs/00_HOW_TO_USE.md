# How to use this package

This folder contains everything needed to build the Tri9T AI internship assignment with
Claude Code (Opus 4.8):

- `01_PRD.md` — what to build and why (product-level requirements).
- `02_TRD.md` — how to build it (data model, API spec, algorithms, repo layout). This is the
  spec Claude Code will read and build against, and will also **update in place** as it
  discovers real facts about the actual manual document.
- `03_EXECUTION_PROMPTS.md` — 9 sequential prompts (plus a required Prompt 0) to paste into
  Claude Code, one at a time, to build the whole thing with real incremental commits.

## Before you start

1. **Create the project folder** and `git init` it (or let Prompt 1 do this).
2. **Get the two data files** the assignment references but did not include in the PDF you
   gave me: `data/ct200_manual.md` and `data/ct200_manual_v2.md`. These should have come with
   the assignment as a separate `data/` folder attachment. Put them in `data/` in your new
   project. **Do not let Claude Code invent these** — the entire "discover irregularities"
   part of the assignment is graded on genuine process, and reviewers will notice fabricated
   content.
3. **Get your two credentials** (you said you'd fetch these):
   - `GROQ_API_KEY` — free at console.groq.com.
   - `MONGODB_URI` — a free Atlas cluster connection string, or leave unset to use the local
     JSON-store fallback described in Prompt 1 (fine for this assignment; just say so in the
     approach doc if you use it).
   You don't need these until Prompt 6 (LLM generation). Get them before then.
4. **Copy `docs/01_PRD.md` and `docs/02_TRD.md`** (i.e., this PRD and TRD, renamed to that
   path) into your new project's `docs/` folder — the execution prompts assume they're there.

## Running it

Open Claude Code (Opus 4.8) in the project folder. Paste **Prompt 0** first and read its
output carefully before continuing — it should describe real structural quirks in your real
`ct200_manual.md`, not generic markdown edge cases. Then paste Prompts 1 through 8 in order,
reviewing the diff and any commit after each one. Don't paste two prompts back to back without
looking at what happened in between — several later prompts depend on real findings from
earlier ones (e.g., Prompt 3 needs to know what Prompt 2 actually found).

## When it's done

- Run the test suite and the demo script yourself once, don't just trust the final commit
  message.
- Read `docs/APPROACH.md` end to end — you need to be able to defend every sentence of it live,
  per the assignment's note about being shortlisted.
- Push to a real GitHub repo (public or shared with the reviewer) — a zip alone doesn't satisfy
  "we will look at your commit history."
- Send the submission email with the repo link and a link/attachment for the approach doc.

## If you want, I can also

- Review the generated `docs/APPROACH.md` and decision log once you have it and pressure-test
  your answers before you submit.
- Help you prep for the "make a live change to it if shortlisted" ask — e.g., mock a change
  request and see if your architecture actually absorbs it cleanly.
