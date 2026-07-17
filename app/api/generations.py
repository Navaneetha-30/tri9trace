"""Generations / retrieval API (FR5/FR7, TRD section 6).

Staleness flags are added to these responses in stage 8 (FR6/FR7). For now
(stage 6) these return the stored generation docs verbatim; a failed
generation is still inspectable here (TRD section 3: never swallow a failed
response).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.mongo import GenerationStore
from app.db.session import get_db
from app.deps import get_store
from app.generation import generation_to_out
from app.schemas import GenerationOut

router = APIRouter(tags=["generations"])


def _get_doc(store: GenerationStore, gen_id: str) -> dict:
    doc = store.get(gen_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"generation {gen_id} not found")
    return doc


@router.get("/generations/{gen_id}", response_model=GenerationOut)
def get_generation(gen_id: str, store: GenerationStore = Depends(get_store)) -> GenerationOut:
    return GenerationOut(**generation_to_out(_get_doc(store, gen_id)))


@router.get("/generations", response_model=list[GenerationOut])
def list_generations(
    selection_id: int | None = Query(None),
    node_id: int | None = Query(None),
    store: GenerationStore = Depends(get_store),
) -> list[GenerationOut]:
    if selection_id is None and node_id is None:
        raise HTTPException(status_code=400, detail="provide ?selection_id= or ?node_id=")
    if selection_id is not None:
        docs = store.list_by_selection(selection_id)
    else:
        docs = store.list_by_node(node_id)  # type: ignore[arg-type]
    return [GenerationOut(**generation_to_out(d)) for d in docs]