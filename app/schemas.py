"""Pydantic request/response schemas for the API surface (TRD section 6)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---- Ingestion ----
class IngestRequest(BaseModel):
    slug: str
    title: str
    file_path: str


class IngestResponse(BaseModel):
    document_id: int
    version_number: int  # DocumentVersion.id
    version_index: int  # 1-based version number
    source_filename: str
    node_count: int
    warnings: list[str] = []


# ---- Browse ----
class SectionOut(BaseModel):
    node_id: int
    logical_key: str
    heading_text: str
    level: int
    order_in_parent: int
    changed_from_previous: bool


class ChildOut(BaseModel):
    node_id: int
    logical_key: str
    heading_text: str
    level: int
    order_in_parent: int


class NodeOut(BaseModel):
    node_id: int
    logical_key: str
    heading_text: str
    level: int
    body_text: str
    content_hash: str
    version: int
    parent_node_id: int | None
    children: list[ChildOut]
    changed_from_previous: bool | None


class SearchResult(BaseModel):
    node_id: int
    logical_key: str
    heading_text: str
    level: int
    version: int
    snippet: str


class DiffResponse(BaseModel):
    node_id: int
    changed: bool
    from_version: int | None
    to_version: int | None
    from_hash: str | None
    to_hash: str | None
    diff_summary: str | None


# ---- Selections ----
class SelectionRequest(BaseModel):
    name: str
    node_ids: list[int]
    version: int | None = None  # None = latest


class SelectionNodeOut(BaseModel):
    node_id: int
    logical_key: str
    heading_text: str
    version: int  # the pinned document version
    content_hash: str
    body_text: str


class SelectionOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    pinned_version: int
    nodes: list[SelectionNodeOut]


# ---- Generations ----
class TestCase(BaseModel):
    title: str
    steps: list[str]
    expected_result: str
    rationale: str
    source_node_ids: list[int] = []


class SourcePin(BaseModel):
    node_id: int
    document_version_id: int
    node_revision_id: int
    content_hash: str
    heading_text: str
    body_text: str


class GenerationOut(BaseModel):
    id: str
    selection_id: int
    generation_index: int
    source_pins: list[SourcePin]
    model: str
    prompt_version: str
    parse_status: str
    retry_count: int
    test_cases: list[TestCase]
    raw_response: str | None = None
    created_at: datetime | None = None
    # staleness (FR6/FR7), filled at retrieval time
    stale: bool | None = None
    stale_nodes: list[int] | None = None
    diff_summary: str | None = None