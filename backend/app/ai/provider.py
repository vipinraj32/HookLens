"""LLM provider interface and the Anthropic implementation.

The graph only depends on `LlmProvider`; tests inject a deterministic fake. The Anthropic
provider calls the official SDK with JSON-schema structured output and server-side refusal
fallback.
"""

from __future__ import annotations

import json
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.schemas import strict_schema
from app.config import get_settings
from app.errors import AppError

M = TypeVar("M", bound=BaseModel)


class LlmProvider(Protocol):
    model: str

    def generate(self, system: str, user: str, schema: type[M]) -> M: ...


class AiRefused(AppError):
    def __init__(self, category: str | None) -> None:
        super().__init__(
            "ai_refused", f"The model declined to answer (category: {category or 'unspecified'}).", status_code=502
        )


class AnthropicProvider:
    def __init__(self, model: str | None = None) -> None:
        import anthropic

        s = get_settings()
        if not s.ai_enabled:
            raise AppError("ai_unavailable", "HOOKLENS_ANTHROPIC_API_KEY is not configured.", status_code=503)
        assert s.anthropic_api_key is not None
        self.model = model or s.ai_model
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=s.anthropic_api_key.get_secret_value(), timeout=s.ai_timeout_s, max_retries=2
        )

    def generate(self, system: str, user: str, schema: type[M]) -> M:
        a = self._anthropic
        try:
            resp = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": strict_schema(schema)}},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except a.RateLimitError as e:
            raise AppError(
                "ai_rate_limited", "The AI provider rate-limited the request.", status_code=503, retryable=True
            ) from e
        except a.APIStatusError as e:
            raise AppError(
                "ai_provider_error",
                f"The AI provider returned HTTP {e.status_code}.",
                status_code=502,
                retryable=e.status_code >= 500,
            ) from e
        except a.APIConnectionError as e:
            raise AppError(
                "ai_unreachable", "The AI provider could not be reached.", status_code=503, retryable=True
            ) from e
        if resp.stop_reason == "refusal":
            raise AiRefused(getattr(resp.stop_details, "category", None) if resp.stop_details else None)
        if resp.stop_reason == "max_tokens":
            raise AppError("ai_truncated", "The AI response was truncated.", status_code=502)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as e:
            raise AppError("ai_malformed", "The AI response did not match the required schema.", status_code=502) from e
