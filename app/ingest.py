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

    from app.versioning.matcher import persist_version

    summary = persist_version(db, doc.id, version.id, nodes)

    db.commit()
    return {
        "document_id": doc.id,
        "version_number": version.id,
        "version_index": next_version,
        "source_filename": source_filename,
        "node_count": len(summary["nodes"]),
        "unchanged": summary["unchanged"],
        "changed": summary["changed"],
        "new": summary["new"],
        "warnings": [w.message for w in warnings],
    }
