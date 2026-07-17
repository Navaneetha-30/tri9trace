"""Selections API (FR4, TRD section 6).

A selection is a named set of node_ids pinned to a SPECIFIC document version:
each SelectionNode stores (node_id, document_version_id, node_revision_id).
A later re-ingestion creating a new version never silently changes what an
old selection refers to -- it is frozen to exact node+version content.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import Node, NodeRevision, Selection, SelectionNode
from app.db.session import get_db
from app.queries import revision_for_node_at_version, version_id_for
from app.schemas import SelectionNodeOut, SelectionOut, SelectionRequest

router = APIRouter(prefix="/selections", tags=["selections"])


@router.post("", response_model=SelectionOut)
def create_selection(
    req: SelectionRequest,
    db: Session = Depends(get_db),
) -> SelectionOut:
    if not req.node_ids:
        raise HTTPException(status_code=400, detail="node_ids must not be empty")

    nodes = [db.get(Node, nid) for nid in req.node_ids]
    if any(n is None for n in nodes):
        missing = [nid for nid, n in zip(req.node_ids, nodes) if n is None]
        raise HTTPException(status_code=404, detail=f"nodes not found: {missing}")
    doc_ids = {n.document_id for n in nodes}  # type: ignore[union-attr]
    if len(doc_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="all node_ids must belong to the same document",
        )
    document_id = doc_ids.pop()

    vid = version_id_for(db, document_id, req.version)
    if vid is None:
        raise HTTPException(status_code=404, detail=f"version {req.version!r} not found")

    # Resolve each node to its exact revision at the pinned version.
    pins: list[tuple[Node, NodeRevision]] = []
    for node in nodes:  # type: ignore[assignment]
        rev = revision_for_node_at_version(db, node.id, vid)
        if rev is None:
            raise HTTPException(
                status_code=400,
                detail=f"node {node.id} has no snapshot in version {req.version} (removed)",
            )
        pins.append((node, rev))

    sel = Selection(name=req.name)
    db.add(sel)
    db.flush()
    for node, rev in pins:
        db.add(
            SelectionNode(
                selection_id=sel.id,
                node_id=node.id,
                document_version_id=vid,
                node_revision_id=rev.id,
            )
        )
    db.commit()
    db.refresh(sel)
    return _to_out(db, sel)


@router.get("/{selection_id}", response_model=SelectionOut)
def get_selection(selection_id: int, db: Session = Depends(get_db)) -> SelectionOut:
    sel = db.get(Selection, selection_id)
    if sel is None:
        raise HTTPException(status_code=404, detail=f"selection {selection_id} not found")
    return _to_out(db, sel)


def _to_out(db: Session, sel: Selection) -> SelectionOut:
    out_nodes: list[SelectionNodeOut] = []
    pinned_version = None
    for item in sel.items:
        rev = db.get(NodeRevision, item.node_revision_id)
        node = db.get(Node, item.node_id)
        pinned_version = item.document_version_id
        out_nodes.append(
            SelectionNodeOut(
                node_id=item.node_id,
                logical_key=node.logical_key if node else "",
                heading_text=rev.heading_text if rev else "",
                version=item.document_version_id,
                content_hash=rev.content_hash if rev else "",
                body_text=rev.body_text if rev else "",
            )
        )
    return SelectionOut(
        id=sel.id,
        name=sel.name,
        created_at=sel.created_at,
        pinned_version=pinned_version,
        nodes=out_nodes,
    )