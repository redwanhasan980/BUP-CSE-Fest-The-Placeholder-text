from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from app.config import settings
from app.llm.prompt import build_messages
from app.schemas import IRResponse

logger = logging.getLogger("gridwise.llm")

# A provider is a callable: (notes, repair_reasons) -> IRResponse. It raises on failure.
Provider = Callable[[list[str], "list[str] | None"], IRResponse]

# Transient errors worth a short backoff-and-retry before giving up on this provider.
_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
_MAX_RETRIES = 2
_BASE_BACKOFF_SECONDS = 0.5
_MIN_CALL_TIMEOUT_SECONDS = 1.0
_DEADLINE_SAFETY_MARGIN_SECONDS = 0.5


@dataclass
class ProviderSpec:
    name: str
    api_key: str
    base_url: str
    model: str


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _call_timeout(deadline: Optional[float]) -> float:
    """Per-call timeout: never exceed what's actually left of the request budget."""
    if deadline is None:
        return settings.llm_timeout_seconds
    remaining = deadline - time.monotonic() - _DEADLINE_SAFETY_MARGIN_SECONDS
    return max(_MIN_CALL_TIMEOUT_SECONDS, min(settings.llm_timeout_seconds, remaining))


def _make_provider(spec: ProviderSpec, deadline: Optional[float] = None) -> Provider:
    client = OpenAI(api_key=spec.api_key, base_url=spec.base_url,
                    timeout=settings.llm_timeout_seconds, max_retries=0)

    def call(notes: list[str], repair_reasons: list[str] | None = None) -> IRResponse:
        messages = build_messages(notes, repair_reasons)
        attempt = 0
        while True:
            if deadline is not None and deadline - time.monotonic() <= _MIN_CALL_TIMEOUT_SECONDS:
                raise TimeoutError(f"provider {spec.name}: no time left in request deadline")
            try:
                resp = client.chat.completions.create(
                    model=spec.model,
                    messages=messages,
                    temperature=0,
                    max_tokens=1200,
                    response_format={"type": "json_object"},
                    timeout=_call_timeout(deadline),
                )
                content = resp.choices[0].message.content or "{}"
                return IRResponse.model_validate(json.loads(content))
            except _RETRYABLE as exc:
                if attempt >= _MAX_RETRIES:
                    raise
                backoff = _retry_after_seconds(exc)
                if backoff is None:
                    backoff = _BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.25)
                if deadline is not None:
                    room = deadline - time.monotonic() - _DEADLINE_SAFETY_MARGIN_SECONDS
                    if room <= 0:
                        raise
                    backoff = min(backoff, room)
                logger.warning("provider %s transient %s; retrying in %.2fs (attempt %d/%d)",
                               spec.name, type(exc).__name__, backoff, attempt + 1, _MAX_RETRIES)
                time.sleep(backoff)
                attempt += 1

    call.__name__ = f"provider_{spec.name}"
    return call


def build_providers(deadline: Optional[float] = None) -> list[Provider]:
    specs: list[ProviderSpec] = []
    if settings.llm_primary_api_key:
        specs.append(ProviderSpec("primary", settings.llm_primary_api_key,
                                  settings.llm_primary_base_url, settings.llm_primary_model))
    if settings.llm_secondary_api_key:
        specs.append(ProviderSpec("secondary", settings.llm_secondary_api_key,
                                  settings.llm_secondary_base_url, settings.llm_secondary_model))
    return [_make_provider(s, deadline) for s in specs]
