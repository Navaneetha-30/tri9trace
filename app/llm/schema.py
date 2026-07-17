"""Pydantic schema for the LLM test-case output (TRD section 7).

The model must return ONLY a JSON object: {"test_cases": [ ... ]} with 3-5
items each matching {title, steps[], expected_result, rationale, source_node_ids[]}.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TestCase(BaseModel):
    title: str
    steps: list[str]
    expected_result: str
    rationale: str
    source_node_ids: list[int] = Field(default_factory=list)


class TestCaseList(BaseModel):
    test_cases: list[TestCase]

    @field_validator("test_cases")
    @classmethod
    def _count(cls, v: list[TestCase]) -> list[TestCase]:
        if not (3 <= len(v) <= 5):
            raise ValueError(f"expected 3-5 test cases, got {len(v)}")
        return v