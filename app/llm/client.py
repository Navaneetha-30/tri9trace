"""LLM provider interface + Groq wrapper (TRD section 1/7).

Primary completion uses Groq's JSON mode (response_format=json_object) for
structured output. If the model emits JSON that Groq's validator rejects
(400 json_validate_failed, which carries a 'failed_generation' field), we
fall back to a PLAIN completion for that call and return its raw text so the
caller's Pydantic validation + retry can handle it. This keeps structured
output as the happy path while not losing borderline-but-fixable outputs.
"""
from __future__ import annotations

from app.config import get_settings


class LLMProvider:
    """Swappable provider interface."""

    model_id: str

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set; the /generate route needs it."
            )
        from groq import Groq

        self._client = Groq(api_key=settings.groq_api_key)
        self.model_id = settings.groq_model

    def _create(self, system: str, user: str, json_mode: bool):
        return self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"} if json_mode else None,
        )

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self._create(system, user, json_mode=True)
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            # Groq 400 json_validate_failed carries the near-miss generation.
            failed = getattr(exc, "response", None)
            body = ""
            try:
                if failed is not None:
                    data = failed.json()
                    body = data.get("error", {}).get("failed_generation", "") or ""
            except Exception:  # noqa: BLE001
                body = ""
            if body:
                # Return the near-miss so the validation/retry path handles it
                # (this preserves the raw output for audit, never fabricating).
                return body
            # Last resort: a plain completion without JSON-mode enforcement.
            resp = self._create(system, user, json_mode=False)
            return resp.choices[0].message.content or ""


class FakeLLM(LLMProvider):
    """Deterministic provider for offline tests."""

    def __init__(self, responses: list[str], model_id: str = "fake") -> None:
        self._responses = responses
        self.model_id = model_id
        self._i = 0

    def complete(self, system: str, user: str) -> str:
        idx = min(self._i, len(self._responses) - 1)
        self._i += 1
        return self._responses[idx]