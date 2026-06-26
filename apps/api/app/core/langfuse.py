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

import threading

from langfuse import Langfuse

from app.config import get_settings

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
                )
            except Exception as exc:
                raise RuntimeError(
                    "Failed to initialise Langfuse — check LANGFUSE_PUBLIC_KEY, "
                    f"LANGFUSE_SECRET_KEY, and LANGFUSE_HOST. Error: {exc}"
                ) from exc
        return _langfuse  # type: ignore[return-value]
