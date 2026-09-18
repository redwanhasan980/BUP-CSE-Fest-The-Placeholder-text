from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional

from app.config import settings
from app.directives import Directive
from app.guardrails import validate
from app.llm.client import Provider, build_providers
from app.llm.rule_fallback import rule_fallback
from app.normalizer import normalize_ir

logger = logging.getLogger("gridwise.interpreter")

_CACHE: "OrderedDict[str, list[Directive]]" = OrderedDict()
_CACHE_MAX = 512


def _cache_key(notes: list[str], capacity: float) -> str:
    payload = "".join(notes) + f"|cap={capacity}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expired(deadline: Optional[float]) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _try_provider(provider: Provider, notes: list[str], capacity: float,
                  deadline: Optional[float] = None) -> Optional[list[Directive]]:
    """One provider: initial call + at most one repair. Returns valid
    directives or None if it could not produce a clean interpretation."""
    try:
        ir = provider(notes, None)
    except Exception as exc:  # network/timeout/parse
        logger.warning("provider %s failed: %s", getattr(provider, "__name__", "?"), type(exc).__name__)
        return None

    directives = normalize_ir(ir, capacity)
    reasons = validate(directives, len(notes), capacity)
    if not reasons:
        return directives

    for _ in range(max(0, settings.llm_max_repair_attempts)):
        if _expired(deadline):
            return None
        try:
            ir = provider(notes, reasons)
        except Exception:
            return None
        directives = normalize_ir(ir, capacity)
        reasons = validate(directives, len(notes), capacity)
        if not reasons:
            return directives
    return None


def interpret(
    notes: list[str],
    capacity: float,
    providers: Optional[list[Provider]] = None,
    enable_fallback: Optional[bool] = None,
    use_cache: bool = True,
    deadline: Optional[float] = None,
) -> tuple[list[Directive], bool]:
    """Interpret notes into validated directives.

    Returns (directives, degraded) where degraded=True means the rule-based
    fallback was used because every LLM attempt failed.
    """
    key = _cache_key(notes, capacity)
    if use_cache and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key], False

    if providers is None:
        providers = build_providers(deadline)
    if enable_fallback is None:
        enable_fallback = settings.enable_rule_fallback

    for provider in providers:
        if _expired(deadline):
            break
        result = _try_provider(provider, notes, capacity, deadline)
        if result is not None:
            if use_cache:
                _store(key, result)
            return result, False

    # All LLM attempts failed -> degraded mode.
    if enable_fallback:
        logger.warning("DEGRADED_MODE: all providers failed; using rule fallback")
        directives = rule_fallback(notes, capacity)
    else:
        directives = [Directive(i, "no_op", explanation="Interpretation unavailable.")
                      for i in range(len(notes))]
    return directives, True


def _store(key: str, directives: list[Directive]) -> None:
    _CACHE[key] = directives
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def clear_cache() -> None:
    _CACHE.clear()
