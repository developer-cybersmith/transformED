"""
Global Langfuse singleton.

One Langfuse client per process. All providers and pipeline nodes call
get_langfuse() instead of constructing their own instance — this prevents
buffered traces from being lost when Railway recycles a container before a
short-lived instance can flush.

Shutdown contract: call get_langfuse().flush() in the FastAPI lifespan
finally block so all buffered spans are sent before the process exits.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from langfuse import Langfuse
from langfuse.types import TraceContext

from app.config import get_settings

logger = logging.getLogger(__name__)

_langfuse: Langfuse | None = None
_lock: threading.Lock = threading.Lock()


def get_langfuse() -> Langfuse:
    """Return the process-wide Langfuse singleton, creating it on first call.

    Thread-safe: uses a lock so concurrent callers at startup never construct
    two separate instances.
    """
    global _langfuse
    with _lock:
        if _langfuse is None:
            settings = get_settings()
            try:
                _langfuse = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                    # Langfuse-skill self-audit finding: without this, every
                    # trace (dev, this session's manual self-audit call,
                    # staging, real production lessons) lands under the
                    # SDK's default "default" environment — see
                    # settings.langfuse_environment's docstring.
                    environment=settings.langfuse_environment,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Failed to initialise Langfuse — check LANGFUSE_PUBLIC_KEY, "
                    f"LANGFUSE_SECRET_KEY, and LANGFUSE_HOST. Error: {exc}"
                ) from exc
        return _langfuse


def safe_trace(call: Callable[[], Any]) -> Any | None:  # noqa: ANN401
    """Run a Langfuse tracing call; observability failures must NEVER fail the
    pipeline. Shared home for the pattern every provider duplicated locally —
    new providers should import this rather than redefine it.
    """
    try:
        return call()
    except Exception:
        # WARNING (not DEBUG): an observability outage must be visible in prod
        # logs even though it never fails the pipeline.
        logger.warning("Langfuse tracing call failed — ignored, pipeline continues", exc_info=True)
        return None


def deterministic_trace_context(langfuse: Langfuse, seed: str | None) -> TraceContext | None:
    """Deterministic `trace_context` so every call sharing the same *seed*
    lands under ONE trace in the Langfuse UI, instead of each call starting
    its own unrelated top-level trace.

    Generic over whatever application-level id groups a set of calls — a
    pipeline `lesson_id` (every provider call across all 11 nodes for one
    lesson) or a tutor `session_id` (every FSM dispatch for one session) are
    both just seeds. Each independent `start_observation()` call is a
    separate invocation with no shared parent call stack to propagate an
    "active span" through (LangGraph's Send()-based fan-out runs Phase 1
    nodes in parallel; the tutor FSM is dispatched per WebSocket event), so
    implicit context nesting (the usual `start_as_current_observation`
    pattern) cannot link them. `Langfuse.create_trace_id(seed=...)`
    sidesteps that: the SAME seed always produces the SAME trace_id,
    regardless of which node, task, or process made the call.

    Returns None (not a partial/broken context) when *seed* is absent (e.g. a
    provider constructed outside a pipeline run) or when Langfuse itself
    errors computing the id — callers pass this straight into
    `trace_context=`, and `start_observation` treats None as "use a random
    trace_id", which is the correct degrade path either way.
    """
    if seed is None:
        return None
    trace_id = safe_trace(lambda: langfuse.create_trace_id(seed=seed))
    if trace_id is None:
        return None
    return TraceContext(trace_id=trace_id)
