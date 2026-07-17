"""Staleness / impact detection (FR6, TRD section 8).

At retrieval time, for each source_pins entry of a stored generation:
  current_revision = latest NodeRevision for source_pins[i].node_id
  stale_i = (current_revision is None)            # node removed in latest version
         OR (current_revision.content_hash != source_pins[i].content_hash)
  generation.stale = any(stale_i)
  generation.stale_nodes = [node_id where stale_i]

A diff_summary is produced for each stale node with difflib, summarized
(not a raw dump): counts of added/removed lines + the first changed line.

STATED LIMITATION (assignment explicit ask): this is a BINARY content-hash
flag. A whitespace/typo fix and a changed safety threshold (e.g. cuff pressure
limit) produce an IDENTICAL signal -- "stale". The system does not currently
weight WHAT KIND of change occurred. A deferred improvement (semantic diff
flagging numeric/threshold changes as high-severity vs. prose-only as
low-severity) is named in docs/APPROACH.md.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Node, NodeRevision
from app.queries import diff_summary
from app.queries import diff_summary, revision_for_node_at_version, version_id_for


def compute_staleness(db: Session, gen_doc: dict) -> dict:
    """Compute staleness for one stored generation doc.

    Returns {"stale": bool, "stale_nodes": [int], "diff_summaries": {node_id: str}}.
    """
    stale_nodes: list[int] = []
    diff_summaries: dict[int, str] = {}
    pins = gen_doc.get("source_pins", [])
    for pin in pins:
        node_id = pin["node_id"]
        node = db.get(Node, node_id)
        # Compare against the node's revision in the CURRENT latest document
        # version (not the node's own latest revision -- a removed node still
        # has its old revision and must be treated as removed/stale here).
        current = None
        if node is not None:
            latest_vid = version_id_for(db, node.document_id, "latest")
            if latest_vid is not None:
                current = revision_for_node_at_version(db, node_id, latest_vid)
        pinned_hash = pin["content_hash"]
        if current is None:
            stale_nodes.append(node_id)
            diff_summaries[node_id] = "node removed in current version"
            continue
        if current.content_hash != pinned_hash:
            stale_nodes.append(node_id)
            diff_summaries[node_id] = diff_summary(pin.get("body_text", ""), current.body_text)
    return {
        "stale": bool(stale_nodes),
        "stale_nodes": stale_nodes,
        "diff_summaries": diff_summaries,
    }