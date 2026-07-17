"""Read-side queries for the browse API (FR3, TRD section 6)."""
from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentVersion, Node, NodeRevision


def get_document_by_slug(db: Session, slug: str) -> Document | None:
    return db.query(Document).filter(Document.slug == slug).one_or_none()


def version_id_for(db: Session, document_id: int, version: int | str | None) -> int | None:
    """Resolve a version spec to a DocumentVersion.id.

    None or 'latest' -> the highest version_number for the document.
    An int -> that exact version_number (None if it doesn't exist).
    """
    if version is None or version == "latest":
        v = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .first()
        )
        return v.id if v else None
    n = int(version)
    v = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_number == n,
        )
        .one_or_none()
    )
    return v.id if v else None


def latest_version_number(db: Session, document_id: int) -> int | None:
    v = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )
    return v.version_number if v else None


def revision_for_node_at_version(
    db: Session, node_id: int, document_version_id: int
) -> NodeRevision | None:
    return (
        db.query(NodeRevision)
        .filter(
            NodeRevision.node_id == node_id,
            NodeRevision.document_version_id == document_version_id,
        )
        .one_or_none()
    )


def top_level_nodes(db: Session, document_id: int, document_version_id: int) -> list[NodeRevision]:
    """Top-level content sections at a version.

    CT-200 manuals have a single '# Title' heading whose children are the
    real content sections (## ...). So if there is exactly one root heading
    (parent is None), we return ITS children; if a document has no single
    title (several top-level headings), we return those root nodes directly.
    """
    roots = (
        db.query(NodeRevision)
        .filter(
            NodeRevision.document_version_id == document_version_id,
            NodeRevision.parent_node_id.is_(None),
        )
        .order_by(NodeRevision.order_in_parent)
        .all()
    )
    if len(roots) == 1:
        return children_of(db, roots[0].node_id, document_version_id)
    return roots


def children_of(
    db: Session, parent_node_id: int, document_version_id: int
) -> list[NodeRevision]:
    return (
        db.query(NodeRevision)
        .filter(
            NodeRevision.document_version_id == document_version_id,
            NodeRevision.parent_node_id == parent_node_id,
        )
        .order_by(NodeRevision.order_in_parent)
        .all()
    )


def search_nodes(
    db: Session, document_id: int, document_version_id: int, q: str
) -> list[tuple[Node, NodeRevision]]:
    """Match heading or body text (case-insensitive) at a version."""
    like = f"%{q}%"
    rows = (
        db.query(Node, NodeRevision)
        .join(NodeRevision, NodeRevision.node_id == Node.id)
        .filter(
            Node.document_id == document_id,
            NodeRevision.document_version_id == document_version_id,
        )
        .filter(Node.heading_text.ilike(like) | NodeRevision.body_text.ilike(like))
        .all()
    )
    return rows


def diff_summary(from_text: str, to_text: str) -> str:
    """A summarized unified diff: counts of added/removed lines + first changed
    line (TRD section 8: summarized, not a raw dump, to keep responses usable)."""
    from_lines = from_text.splitlines() or [""]
    to_lines = to_text.splitlines() or [""]
    diff = list(difflib.unified_diff(from_lines, to_lines, lineterm=""))
    if not diff:
        return ""
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    first_change = next((l[1:] for l in diff if l[:1] in "+-" and l[:2] not in ("++", "--")), "")
    return f"+{added} -{removed} lines; first change: {first_change!r}"


def node_diff(
    db: Session, node_id: int, from_version_id: int, to_version_id: int
) -> dict:
    from_rev = revision_for_node_at_version(db, node_id, from_version_id)
    to_rev = revision_for_node_at_version(db, node_id, to_version_id)
    out = {
        "node_id": node_id,
        "changed": False,
        "from_version": None,
        "to_version": None,
        "from_hash": None,
        "to_hash": None,
        "diff_summary": None,
    }
    if from_rev:
        out["from_version"] = from_rev.document_version_id
        out["from_hash"] = from_rev.content_hash
    if to_rev:
        out["to_version"] = to_rev.document_version_id
        out["to_hash"] = to_rev.content_hash
    if from_rev and to_rev:
        out["changed"] = from_rev.content_hash != to_rev.content_hash
        if out["changed"]:
            out["diff_summary"] = diff_summary(from_rev.body_text, to_rev.body_text)
    return out