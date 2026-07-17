"""FastAPI dependencies for the generation flow: an LLM provider and a
generation store. Built lazily as module singletons so we don't open a Mongo
client or require a Groq key until /generate is actually called (browse and
ingestion stay zero-external-service). Tests override these via
app.dependency_overrides to inject a FakeLLM and an in-memory/JSON store.
"""
from __future__ import annotations

from app.db.mongo import GenerationStore, get_generation_store
from app.llm.client import GroqProvider, LLMProvider

_llm: LLMProvider | None = None
_store: GenerationStore | None = None


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = GroqProvider()
    return _llm


def get_store() -> GenerationStore:
    global _store
    if _store is None:
        _store = get_generation_store()
    return _store