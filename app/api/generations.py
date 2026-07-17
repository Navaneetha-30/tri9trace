"""Generations / retrieval API (FR5/FR7, TRD section 6/8).

Every generation returned carries a staleness flag computed at retrieval
time (FR6) -- a correct staleness check that isn't queryable here doesn't
count as done. Failed generations remain inspectable (never swallowed).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.mongo import GenerationStore
from app.db.session import get_db
from app.deps import get_store
from app.generation import generation_to_out
from app.schemas import GenerationOut
from app.versioning.staleness import compute_staleness

router = APIRouter(tags=["generations"])


def _get_doc(store: GenerationStore, gen_id: str) -> dict:
    doc = store.get(gen_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"generation {gen_id} not found")
    return doc


def _with_staleness(db: Session, doc: dict) -> dict:
    out = generation_to_out(doc)
    st = compute_staleness(db, doc)
    out["stale"] = st["stale"]
    out["stale_nodes"] = st["stale_nodes"]
    # Join per-node diff summaries into one short string for the response.
    if st["stale_nodes"]:
        parts = [f"node {nid}: {st['diff_summaries'][nid]}" for nid in st["stale_nodes"]]
        out["diff_summary"] = " | ".join(parts)
    else:
        out["diff_summary"] = None
    return out


@router.get("/generations/{gen_id}", response_model=GenerationOut)
def get_generation(
    gen_id: str,
    db: Session = Depends(get_db),
    store: GenerationStore = Depends(get_store),
) -> GenerationOut:
    return GenerationOut(**_with_staleness(db, _get_doc(store, gen_id)))


@router.get("/generations", response_model=list[GenerationOut])
def list_generations(
    selection_id: int | None = Query(None),
    node_id: int | None = Query(None),
    db: Session = Depends(get_db),
    store: GenerationStore = Depends(get_store),
) -> list[GenerationOut]:
    if selection_id is None and node_id is None:
        raise HTTPException(status_code=400, detail="provide ?selection_id= or ?node_id=")
    docs = store.list_by_selection(selection_id) if selection_id is not None else store.list_by_node(node_id)
    return [GenerationOut(**_with_staleness(db, d)) for d in docs]