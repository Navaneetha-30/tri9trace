"""SQLAlchemy models for the relational store (TRD section 2).

Two-tier node identity:
- Node: a STABLE logical id for "this section" across the document's life.
- NodeRevision: a frozen per-version snapshot of that section's text + tree
  position. Staleness (FR6) is just: does the NodeRevision a generation was
  pinned to equal the latest NodeRevision for that Node?

Selections pin (node, document_version, node_revision) triples so a later
re-ingestion never silently changes what an old selection refers to.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    document: Mapped["Document"] = relationship(back_populates="versions")


class Node(Base):
    """Stable logical node. Survives across versions. Matched by logical_key."""

    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("document_id", "logical_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    first_seen_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    logical_key: Mapped[str] = mapped_column(String, nullable=False)
    heading_text: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)


class NodeRevision(Base):
    """One row per node PER version it appears in."""

    __tablename__ = "node_revisions"
    __table_args__ = (UniqueConstraint("node_id", "document_version_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    parent_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id"), nullable=True
    )
    heading_text: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    order_in_parent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_changed_from_previous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    node: Mapped["Node"] = relationship(foreign_keys=[node_id])


class Selection(Base):
    __tablename__ = "selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    items: Mapped[list["SelectionNode"]] = relationship(
        back_populates="selection", cascade="all, delete-orphan"
    )


class SelectionNode(Base):
    """A version-pinned member of a selection: exact node+version+revision."""

    __tablename__ = "selection_nodes"
    __table_args__ = (UniqueConstraint("selection_id", "node_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"), nullable=False)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    node_revision_id: Mapped[int] = mapped_column(
        ForeignKey("node_revisions.id"), nullable=False
    )

    selection: Mapped["Selection"] = relationship(back_populates="items")