"""FastAPI application entrypoint.

Wires routers, creates SQLite tables on startup, exposes /health.
Ingestion + browse need no external services; /generate needs Groq + a store.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import documents, generations, nodes, selections
from app.db.session import init_db

app = FastAPI(
    title="CT-200 QA Tracer",
    description="QA traceability & test-case generation for the CT-200 manual.",
    version="1.0.0",
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(documents.router)
app.include_router(nodes.router)
app.include_router(selections.router)
app.include_router(generations.router)