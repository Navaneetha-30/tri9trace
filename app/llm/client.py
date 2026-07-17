"""LLM provider interface + Groq wrapper (TRD section 1/7)."""
from __future__ import annotations

from app.config import get_settings


class LLMProvider:
    """Swappable provider interface."""

    model_id: str

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    """Groq chat completion wrapper. Reads GROQ_API_KEY from env at startup
    and raises a clear error (not a silent None) if it is missing."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set; the /generate route needs it."
            )
        from groq import Groq

        self._client = Groq(api_key=settings.groq_api_key)
        self.model_id = settings.groq_model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""


class FakeLLM(LLMProvider):
    """Deterministic provider for offline tests. Returns a fixed payload, or
    a malformed payload then a valid one to exercise the retry path."""

    def __init__(self, responses: list[str], model_id: str = "fake") -> None:
        self._responses = responses
        self.model_id = model_id
        self._i = 0

    def complete(self, system: str, user: str) -> str:
        idx = min(self._i, len(self._responses) - 1)
        self._i += 1
        return self._responses[idx]