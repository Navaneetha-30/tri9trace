"""Documents API (FR1 ingestion)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ingest import IngestError, ingest_file
from app.schemas import IngestRequest, IngestResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    try:
        result = ingest_file(db, req.slug, req.title, req.file_path)
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return IngestResponse(**result)