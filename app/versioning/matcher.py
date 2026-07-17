"""Version matching across re-ingestion (FR2, TRD section 5).

Strategy: path-based logical key + content-hash confirmation.

- logical_key = slug(path of ancestor headings + this heading), computed
  identically at every ingestion.
- On re-ingest, for each parsed node:
    * existing Node with same (document, logical_key) -> reuse Node.id, create
      a new NodeRevision under the new DocumentVersion, set
      is_changed_from_previous = (new content_hash != prior revision's hash).
    * no existing Node -> new Node (first_seen = this version), new revision,
      is_changed = False (nothing to compare against).
- A previous Node whose logical_key is absent from the new version is NOT
  deleted (history must survive); it simply gets no NodeRevision for the new
  DocumentVersion. The browse API derives "removed in v_n" at query time by
  noticing the node's latest revision is in an older version.

Known limitation (stated in APPROACH.md): if a section is renamed AND its
content changes in the same version bump, this sees it as a delete + a
brand-new node, losing the "same logical thing" link. Fuzzy title matching
would reduce this failure mode but introduce false-positive matches, so we
deliberately do not do it.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, Node, NodeRevision
from app.parsing.parser import ParseWarning
from app.parsing.tree import content_hash


def persist_version(
    db: Session,
    document_id: int,
    version_id: int,
    parsed_nodes: list,
) -> dict:
    """Create/mmatch Nodes and per-version NodeRevisions for a new ingest.

    Returns a summary with per-node change classification for inspection.
    """
    key_to_node_id: dict[str, int] = {}

    # Index existing logical nodes for this document.
    existing: dict[str, Node] = {
        n.logical_key: n
        for n in db.query(Node).filter(Node.document_id == document_id).all()
    }

    summary = {"unchanged": 0, "changed": 0, "new": 0, "nodes": []}

    for parsed in parsed_nodes:
        key = parsed.logical_key
        parent_id = key_to_node_id.get(parsed.parent.logical_key) if parsed.parent else None
        new_hash = content_hash(parsed.heading_text, parsed.body_text)

        if key in existing:
            node = existing[key]
            # Most recent prior revision for this node (before this version).
            prior = (
                db.query(NodeRevision)
                .filter(NodeRevision.node_id == node.id)
                .order_by(NodeRevision.document_version_id.desc())
                .first()
            )
            is_changed = bool(prior is None or prior.content_hash != new_hash)
            if is_changed:
                summary["changed"] += 1
            else:
                summary["unchanged"] += 1
        else:
            node = Node(
                document_id=document_id,
                first_seen_version_id=version_id,
                logical_key=key,
                heading_text=parsed.heading_text,
                level=parsed.level,
            )
            db.add(node)
            db.flush()
            existing[key] = node
            is_changed = False
            summary["new"] += 1

        rev = NodeRevision(
            node_id=node.id,
            document_version_id=version_id,
            parent_node_id=parent_id,
            heading_text=parsed.heading_text,
            level=parsed.level,
            order_in_parent=parsed.order_in_parent,
            body_text=parsed.body_text,
            content_hash=new_hash,
            is_changed_from_previous=is_changed,
        )
        db.add(rev)
        db.flush()
        key_to_node_id[key] = node.id
        summary["nodes"].append(
            {
                "node_id": node.id,
                "logical_key": key,
                "heading_text": parsed.heading_text,
                "status": "unchanged" if key in existing and not is_changed else ("changed" if key in existing else "new"),
            }
        )
    return summary


def latest_revision_for_node(db: Session, node_id: int) -> NodeRevision | None:
    return (
        db.query(NodeRevision)
        .filter(NodeRevision.node_id == node_id)
        .order_by(NodeRevision.document_version_id.desc())
        .first()
    )


def latest_version_number(db: Session, document_id: int) -> int | None:
    latest = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )
    return latest.version_number if latest else None