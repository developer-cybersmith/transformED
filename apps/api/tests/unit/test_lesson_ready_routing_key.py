"""Story 2-37 / D23: `lesson_ready` must publish to `lesson_ready:{lesson_id}`.

Why this file exists
--------------------
`content_pipeline.py` used to build the channel like this::

    # session_id is the WebSocket routing key; falls back to lesson_id until
    # the upload route stores it (Sprint 2 — Dev 4 coordinates)
    session_id: str = lesson_row.get("session_id") or lesson_id
    ...
    channel = f"lesson_ready:{session_id}"

**`lessons` has no `session_id` column.** So `.get("session_id")` was always `None`,
the fallback always fired, and the channel was always `lesson_ready:{lesson_id}` —
the RIGHT answer, produced by ACCIDENT.

Meanwhile `core/websocket.py` registered connections under the client-supplied
`session_id` (`crypto.randomUUID()`), so the keys could never match and the push
reached no client. Dev 4 chose option A (key by `lesson_id`) and now maintains a
`lesson_waiters:{lesson_id}` set to fan out to every waiting session.

The behaviour was already right. What was wrong — and what these tests guard — is
that it depended on a column NOT existing. One unrelated migration adding
`lessons.session_id` would have silently changed the publish key under Dev 4's
routing, with no test failing.

Note for future readers: `test_schema_column_guard.py` does NOT cover this. It walks
`.table(x).select(...)/.eq(...)`; this was a `dict.get()` on an already-fetched row.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_MIGRATIONS = Path(__file__).resolve().parents[2].parents[1] / "supabase" / "migrations"
LESSON_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


async def _publish_calls(row_extra: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Run content_pipeline_job and return every (channel, payload) published.

    AC-2: the assertion has to be on the OBSERVABLE publish. Asserting that a
    local variable equals `lesson_id` would have passed against the accidental
    version too, and would therefore have proved nothing.
    """
    from app.workers.jobs import content_pipeline as cp

    published: list[tuple[str, str]] = []

    redis = AsyncMock()

    async def _capture(channel: str, payload: str) -> None:
        published.append((channel, payload))

    redis.publish = _capture

    row: dict[str, Any] = {
        "lesson_id": LESSON_ID,
        "source_pdf_path": "p.pdf",
        "lessons": {"user_id": "u1", "book_id": "b1", "tier": "T2"},
        **(row_extra or {}),
    }
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.maybe_single.return_value.execute.return_value.data = row
    chain.single.return_value.execute.return_value.data = row
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [row]

    with (
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(return_value={"lesson_id": LESSON_ID, "segments": []}),
        ),
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock(return_value=None)),
        patch("app.core.redis.get_redis", return_value=redis),
    ):
        try:
            await cp.content_pipeline_job({"job_id": "j", "job_try": 1}, LESSON_ID)
        except Exception:  # noqa: BLE001, S110 — only the publish call matters here
            pass

    return published


# ── AC-3: the premise — `lessons` must not gain a session_id column silently ──


async def test_lessons_table_has_no_session_id_column() -> None:
    """The routing contract depends on a SCHEMA FACT, so the schema fact is asserted.

    If this fails, someone has added `lessons.session_id`. That is not necessarily
    wrong — but it silently changes what `lesson_ready` would be keyed by if the
    old `.get("session_id") or lesson_id` pattern ever came back, and it means the
    lesson/session relationship has been modelled. Read Story 2-37 and
    `docs/handoffs/dev4-handoff-2026-07-29.md` §2 before changing the routing key,
    because Dev 4's `lesson_waiters:{lesson_id}` fan-out depends on it.
    """
    assert _MIGRATIONS.is_dir(), f"migrations directory not found at {_MIGRATIONS}"

    sql = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in sorted(_MIGRATIONS.glob("*.sql"))
    )

    # `ALTER TABLE ... lessons ... ADD COLUMN ... session_id`
    altered = re.search(
        r"alter\s+table\s+(?:if\s+exists\s+)?(?:public\.)?lessons\b[^;]*?"
        r"add\s+column\s+(?:if\s+not\s+exists\s+)?session_id\b",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert altered is None, "lessons.session_id was added by an ALTER — see Story 2-37"

    created = re.search(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?lessons\b\s*\((.*?)\n\s*\);",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert created is not None, "could not locate the lessons CREATE TABLE — parser needs updating"
    assert not re.search(r"\bsession_id\b", created.group(1), re.IGNORECASE), (
        "lessons.session_id exists in the initial schema — see Story 2-37"
    )


# ── AC-1 / AC-2: the channel, asserted on the real publish call ──────────────


async def test_lesson_ready_is_published_keyed_by_lesson_id() -> None:
    """Dev 4 option A: generation completion is lesson-scoped, not viewer-scoped."""
    published = await _publish_calls()

    channels = [c for c, _ in published]
    assert channels, "no lesson_ready publish happened at all"
    assert f"lesson_ready:{LESSON_ID}" in channels, (
        f"expected the channel to be keyed by lesson_id, got {channels}"
    )


async def test_channel_ignores_a_session_id_present_on_the_row() -> None:
    """**The test that fails against the accidental version.**

    The old code produced the right channel only because `.get("session_id")`
    always returned `None`. Feed it a row that DOES carry a `session_id` — which is
    exactly what one unrelated migration would create — and the old code publishes
    to `lesson_ready:<that value>`, which nobody is subscribed to.

    Nothing in the codebase may make the routing key depend on this field.
    """
    rogue = "99999999-9999-9999-9999-999999999999"
    published = await _publish_calls({"session_id": rogue})

    channels = [c for c, _ in published]
    assert channels, "no lesson_ready publish happened at all"
    assert f"lesson_ready:{rogue}" not in channels, (
        "the publish key still follows a session_id on the lessons row — that is the "
        "accidental behaviour D23 removed; Dev 4's lesson_waiters fan-out would miss it"
    )
    assert f"lesson_ready:{LESSON_ID}" in channels


# ── AC-4: the payload contract is unchanged ─────────────────────────────────


async def test_payload_shape_is_unchanged() -> None:
    """This story changes the CHANNEL, not the contract — no §16 gate.

    Shape must stay `{type, payload: {lesson_id, lesson}}` per
    `packages/shared/types/ws.ts`.
    """
    import json

    published = await _publish_calls()
    assert published, "no lesson_ready publish happened at all"

    _, raw = published[0]
    message = json.loads(raw)

    assert message["type"] == "lesson_ready"
    assert set(message["payload"]) == {"lesson_id", "lesson"}
    assert message["payload"]["lesson_id"] == LESSON_ID
