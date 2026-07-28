"""
Queue-name constants shared by the API (enqueue side) and the ARQ worker
(consume side).

Single source of truth: both app.main (create_pool default_queue_name) and
app.workers.main (WorkerSettings.queue_name) MUST import PIPELINE_QUEUE from
here — a literal on either side can silently drift and strand 100% of jobs
(the exact failure the 2026-07-08 live E2E exposed).
"""

from __future__ import annotations

PIPELINE_QUEUE = "hie:pipeline"
"""ARQ queue for the content-generation pipeline jobs."""
