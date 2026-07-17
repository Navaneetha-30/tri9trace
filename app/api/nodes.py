"""Nodes / browse API (FR3, TRD section 6).

NOTE on route order: /nodes/search is registered BEFORE /nodes/{node_id} so
the literal 'search' segment is not captured by the int path parameter.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import Node
from app.db.session import get_db
from app.queries import (
    children_of,
    latest_version_number,
    node_diff,
    revision_for_node_at_version,
    version_id_for,
)
from app.schemas import ChildOut, DiffResponse, NodeOut, SearchResult

router = APIRouter(prefix="/nodes", tags=["nodes"])


def _resolve_node(db: Session, node_id: int) -> Node:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"node {node_id} not found")
    return node


@router.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=1),
    version: str | int | None = Query("latest"),
    document_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[SearchResult]:
    from app.db.models import DocumentVersion
    from app.queries import search_nodes

    if document_id is None:
        # Search the latest version across all documents.
        docs = db.query(DocumentVersion).order_by(DocumentVersion.version_number.desc()).all()
        seen: dict[int, int] = {}
        for dv in docs:
            seen.setdefault(dv.document_id, dv.id)
        results: list[SearchResult] = []
        for doc_id, vid in seen.items():
            results.extend(_search_in(db, doc_id, vid, q, search_nodes))
        return results
    vid = version_id_for(db, document_id, version)
    if vid is None:
        raise HTTPException(status_code=404, detail=f"version not found for document {document_id}")
    return _search_in(db, document_id, vid, q, search_nodes)


def _search_in(db, document_id, vid, q, search_nodes) -> list[SearchResult]:
    rows = search_nodes(db, document_id, vid, q)
    out = []
    for node, rev in rows:
        body = rev.body_text or ""
        idx = body.lower().find(q.lower())
        snippet = body[max(0, idx - 40) : idx + 60] if idx >= 0 else ""
        out.append(
            SearchResult(
                node_id=node.id,
                logical_key=node.logical_key,
                heading_text=rev.heading_text,
                level=rev.level,
                version=rev.document_version_id,
                snippet=snippet,
            )
        )
    return out


@router.get("/{node_id}", response_model=NodeOut)
def get_node(
    node_id: int,
    version: str | int | None = Query("latest"),
    db: Session = Depends(get_db),
) -> NodeOut:
    node = _resolve_node(db, node_id)
    vid = version_id_for(db, node.document_id, version)
    if vid is None:
        raise HTTPException(status_code=404, detail=f"version {version!r} not found")
    rev = revision_for_node_at_version(db, node.id, vid)
    if rev is None:
        raise HTTPException(
            status_code=404,
            detail=f"node {node_id} has no snapshot in version {version} (removed)",
        )
    children = children_of(db, node.id, vid)
    return NodeOut(
        node_id=node.id,
        logical_key=node.logical_key,
        heading_text=rev.heading_text,
        level=rev.level,
        body_text=rev.body_text,
        content_hash=rev.content_hash,
        version=rev.document_version_id,
        parent_node_id=rev.parent_node_id,
        children=[
            ChildOut(
                node_id=c.node_id,
                logical_key=c.node.logical_key,
                heading_text=c.heading_text,
                level=c.level,
                order_in_parent=c.order_in_parent,
            )
            for c in children
        ],
        changed_from_previous=rev.is_changed_from_previous,
    )


@router.get("/{node_id}/diff", response_model=DiffResponse)
def node_diff_route(
    node_id: int,
    to: str | int | None = Query("latest"),
    frm: str | int | None = Query(None),
    db: Session = Depends(get_db),
) -> DiffResponse:
    node = _resolve_node(db, node_id)
    to_v = version_id_for(db, node.document_id, to)
    if to_v is None:
        raise HTTPException(status_code=404, detail=f"version {to!r} not found")
    if frm is not None:
        from_v = version_id_for(db, node.document_id, frm)
        d = node_diff(db, node.id, from_v, to_v)
    else:
        latest = latest_version_number(db, node.document_id)
        if to_v == version_id_for(db, node.document_id, latest) and latest and latest > 1:
            from_v = version_id_for(db, node.document_id, latest - 1)
        else:
            from_v = version_id_for(db, node.document_id, latest)
        d = node_diff(db, node.id, from_v, to_v)
    return DiffResponse(**d)