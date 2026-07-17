"""Documents API (FR1 ingestion + FR3 top-level sections)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ingest import IngestError, ingest_file
from app.queries import (
    get_document_by_slug,
    latest_version_number,
    top_level_nodes,
    version_id_for,
)
from app.schemas import IngestRequest, IngestResponse, SectionOut

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    try:
        result = ingest_file(db, req.slug, req.title, req.file_path)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return IngestResponse(**result)


@router.get("/{slug}/sections", response_model=list[SectionOut])
def list_sections(
    slug: str,
    version: str | int | None = Query("latest"),
    db: Session = Depends(get_db),
) -> list[SectionOut]:
    doc = get_document_by_slug(db, slug)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document {slug!r} not found")
    vid = version_id_for(db, doc.id, version)
    if vid is None:
        raise HTTPException(status_code=404, detail=f"version {version!r} not found")
    revs = top_level_nodes(db, doc.id, vid)
    return [
        SectionOut(
            node_id=r.node_id,
            logical_key=r.node.logical_key,
            heading_text=r.heading_text,
            level=r.level,
            order_in_parent=r.order_in_parent,
            changed_from_previous=r.is_changed_from_previous,
        )
        for r in revs
    ]
