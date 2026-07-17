"""Generation orchestration (TRD section 7): selection -> LLM -> validate ->
store, with one retry and full provenance. Pure logic; the LLM provider and
generation store are injected so it is fully testable offline.

Duplicate-submission policy (TRD section 7): every call creates a NEW
generation record (generation_index incremented), never overwriting or
silently deduping. Rationale: LLM output is not idempotent and overwriting
would destroy a QA audit trail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import Selection
from app.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_retry_prompt, build_user_prompt
from app.llm.schema import TestCaseList


def _load_selection_nodes(db: Session, selection_id: int) -> tuple[Selection, list[dict]]:
    sel = db.get(Selection, selection_id)
    if sel is None:
        raise KeyError(f"selection {selection_id} not found")
    nodes = []
    for item in sel.items:
        rev = item.node_revision
        node = item.node
        nodes.append(
            {
                "node_id": node.id,
                "logical_key": node.logical_key,
                "heading_text": rev.heading_text,
                "body_text": rev.body_text,
                "content_hash": rev.content_hash,
                "document_version_id": item.document_version_id,
                "node_revision_id": item.node_revision_id,
            }
        )
    return sel, nodes


def generate_for_selection(db: Session, selection_id: int, llm, store) -> dict[str, Any]:
    sel, nodes = _load_selection_nodes(db, selection_id)

    # Duplicate-submission policy: always a new generation record.
    existing = store.list_by_selection(selection_id)
    generation_index = len(existing)

    user_prompt = build_user_prompt(nodes)
    raw_attempts: list[str] = []
    test_cases = None
    parse_status = "failed"
    retry_count = 0
    validation_error = None

    for attempt in (1, 2):
        raw = llm.complete(SYSTEM_PROMPT, user_prompt)
        raw_attempts.append(raw)
        try:
            parsed = TestCaseList.model_validate_json(raw)
            test_cases = [tc.model_dump() for tc in parsed.test_cases]
            parse_status = "ok" if attempt == 1 else "retried_ok"
            validation_error = None
            break
        except ValidationError as exc:
            validation_error = str(exc).splitlines()[0] or "validation failed"
            retry_count = attempt
            user_prompt = build_retry_prompt(nodes, validation_error)
            continue

    if test_cases is None:
        parse_status = "failed"

    source_pins = [
        {
            "node_id": n["node_id"],
            "document_version_id": n["document_version_id"],
            "node_revision_id": n["node_revision_id"],
            "content_hash": n["content_hash"],
            "heading_text": n["heading_text"],
            "body_text": n["body_text"],
        }
        for n in nodes
    ]

    doc: dict[str, Any] = {
        "selection_id": selection_id,
        "selection_name": sel.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation_index": generation_index,
        "source_pins": source_pins,
        "llm": {"provider": "groq", "model": llm.model_id, "prompt_version": PROMPT_VERSION},
        "raw_response": raw_attempts[-1],
        "raw_attempts": raw_attempts,
        "parse_status": parse_status,
        "retry_count": retry_count,
        "validation_error": validation_error,
        "test_cases": test_cases or [],
    }
    gen_id = store.put(doc)
    doc["id"] = gen_id
    return doc


def generation_to_out(doc: dict) -> dict:
    """Flatten a stored generation doc into the GenerationOut API shape."""
    return {
        "id": str(doc.get("id") or doc.get("_id")),
        "selection_id": doc["selection_id"],
        "generation_index": doc.get("generation_index", 0),
        "source_pins": doc.get("source_pins", []),
        "model": doc.get("llm", {}).get("model", ""),
        "prompt_version": doc.get("llm", {}).get("prompt_version", ""),
        "parse_status": doc.get("parse_status"),
        "retry_count": doc.get("retry_count", 0),
        "test_cases": doc.get("test_cases") or [],
        "raw_response": doc.get("raw_response"),
        "created_at": doc.get("generated_at"),
    }
