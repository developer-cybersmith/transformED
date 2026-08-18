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

import functools
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

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


_State = TypeVar("_State")


def traced_node(
    node_name: str, *, seed_key: str = "lesson_id"
) -> Callable[[Callable[[_State], Awaitable[_State]]], Callable[[_State], Awaitable[_State]]]:
    """Wrap a LangGraph node coroutine with a Langfuse span (D69, node-level half).

    D69 (docs/DEFECT-REGISTER.md): every provider call across an N-node
    pipeline run lands as a flat sibling directly under its trace root, not
    nested under a per-node span -- because nothing ever created a per-node
    span to nest under. This closes exactly that half.

    Uses the SAME deterministic trace_id every provider call already uses
    (`deterministic_trace_context`, seeded by `state[seed_key]`) so each
    node's span lands under the SAME trace as the LLM/TTS/image calls made
    while it runs -- not a second, disconnected trace. Content-pipeline
    nodes seed on `lesson_id` (the default); the tutor FSM deliberately does
    NOT use this decorator at all -- `_trace_dispatch` already traces each
    dispatch correctly as its own event, one node ever runs per `ainvoke()`
    call there, and forcing a shared trace_id across an hour-plus,
    dozens-of-dispatches session is exactly what `_trace_dispatch`'s own
    docstring found wrong with an earlier attempt at this. Do not add this
    to tutor nodes.

    Does NOT nest the provider calls MADE INSIDE each node under that node's
    own span -- doing so needs `parent_span_id` threaded through pipeline
    state into every provider constructor, a real architecture change D69
    itself already scopes as separate and larger. This gives node-level
    timing/grouping (how long did structure_node take, sibling to the calls
    it made) without that bigger, riskier change.

    Never raises and never changes the wrapped node's return value or
    exceptions -- an observability failure must never break the pipeline
    (this file's own established contract, `safe_trace`).
    """

    def decorator(
        fn: Callable[[_State], Awaitable[_State]],
    ) -> Callable[[_State], Awaitable[_State]]:
        @functools.wraps(fn)
        async def wrapper(state: _State) -> _State:
            seed = state.get(seed_key) if isinstance(state, dict) else None  # type: ignore[attr-defined]
            langfuse = get_langfuse()
            trace_context = deterministic_trace_context(langfuse, seed)
            span = safe_trace(
                lambda: langfuse.start_observation(
                    name=node_name,
                    as_type="span",
                    trace_context=trace_context,
                )
            )
            try:
                return await fn(state)
            except Exception as exc:
                if span is not None:
                    error_message = str(exc)
                    safe_trace(lambda: span.update(level="ERROR", status_message=error_message))
                raise
            finally:
                if span is not None:
                    safe_trace(span.end)

        return wrapper

    return decorator
