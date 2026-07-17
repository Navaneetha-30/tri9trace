"""Ingestion pipeline: markdown file -> parse -> persist (TRD section 4/2).

Stage 2 (FR1) implements first-ingest: creates the Document (if new) and a
DocumentVersion numbered 1 with its full node tree (one Node + NodeRevision
per parsed section). Version matching across re-ingestion is added in stage 3
(FR2) via app.versioning.matcher; this module already routes node creation
through match_or_create_node so the stage-3 swap is localized.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Document, DocumentVersion, Node, NodeRevision
from app.parsing.parser import ParseWarning, flatten, parse_markdown
from app.parsing.tree import content_hash


class IngestError(Exception):
    pass


def ingest_file(db: Session, slug: str, title: str, file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise IngestError(f"file not found: {file_path}")
    return ingest_text(db, slug, title, path.name, path.read_text(encoding="utf-8"))


def ingest_text(
    db: Session, slug: str, title: str, source_filename: str, text: str
) -> dict[str, Any]:
    root, warnings = parse_markdown(text)
    nodes = flatten(root)

    doc = db.query(Document).filter(Document.slug == slug).one_or_none()
    if doc is None:
        doc = Document(slug=slug, title=title)
        db.add(doc)
        db.flush()

    next_version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc.id)
        .count()
        + 1
    )
    version = DocumentVersion(
        document_id=doc.id,
        version_number=next_version,
        source_filename=source_filename,
    )
    db.add(version)
    db.flush()

    created_nodes = 0
    for node in nodes:
        match_or_create_node(db, doc.id, version.id, node)
        created_nodes += 1

    db.commit()
    return {
        "document_id": doc.id,
        "version_number": version.id,
        "version_index": next_version,
        "source_filename": source_filename,
        "node_count": created_nodes,
        "warnings": [w.message for w in warnings],
    }


def match_or_create_node(
    db: Session, document_id: int, version_id: int, parsed
) -> Node:
    """Stage 2: always create a fresh logical node (correct for first ingest).

    Stage 3 (FR2) replaces the body of this function with path-based matching
    that reuses an existing Node.id when the same logical_key already exists,
    creating a new NodeRevision under it and setting is_changed_from_previous.
    """
    node = Node(
        document_id=document_id,
        first_seen_version_id=version_id,
        logical_key=parsed.logical_key,
        heading_text=parsed.heading_text,
        level=parsed.level,
    )
    db.add(node)
    db.flush()
    rev = NodeRevision(
        node_id=node.id,
        document_version_id=version_id,
        parent_node_id=None,  # set below after we know parent ids
        heading_text=parsed.heading_text,
        level=parsed.level,
        order_in_parent=parsed.order_in_parent,
        body_text=parsed.body_text,
        content_hash=content_hash(parsed.heading_text, parsed.body_text),
        is_changed_from_previous=False,
    )
    db.add(rev)
    db.flush()
    return node