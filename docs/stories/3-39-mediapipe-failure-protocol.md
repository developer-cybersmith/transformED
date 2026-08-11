# Story 3-39 — MediaPipe Failure Protocol

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 (weight redistribution logic + session_flags migration) + Dev 4 (signal gap detection in WebSocket)
**Status:** ready-for-dev
**Branch:** `sprint3/s3-39-mediapipe-failure-protocol`
**Depends on:** Story 3-38 (NormalizedSignal Optional — must be merged first)

---

## Background

No camera failure detection, alert protocol, or formal redistribution trigger exists anywhere
in the codebase. The current behaviour when MediaPipe is unavailable:

- Before S3-38: `_parse_signal` raises `ValueError` on the first absent MediaPipe field →
  WebSocket process loop crashes or logs an unhandled error.
- After S3-38: `_parse_signal` returns `behavioral=None`, `head_pose=None`, `blink=None` →
  CES redistribution runs correctly, but the student and admin have no visibility into the
  degraded state.

CLAUDE.md §Tutor State Machine: "CES monitoring ONLY active in TEACHING state." When
MediaPipe is limited, the academic signals (quiz_accuracy, teachback_score) carry full weight
via the canonical redistribution — this is mathematically correct behavior (already handled
by `ces.py`). What is missing is:

1. **Alert detection:** count consecutive windows with all 3 MediaPipe signals None.
2. **Alert threshold:** 3 consecutive windows (= 15 s of no camera signal) → flag.
3. **Client notification:** WebSocket message to the frontend (to show a UI banner).
4. **Session flag:** `sessions.session_flags` does not exist. Migration needed.
5. **Admin visibility:** `session_flags.mediapipe_limited = true` persisted to DB.

### Defect Record

| ID | Description | Status |
|----|-------------|--------|
| D68 | No camera failure detection, alert, or redistribution trigger | Opened by S3-39 |

---

## Acceptance Criteria

### AC 1 — session_flags migration
New migration `supabase/migrations/20260811000000_session_flags.sql`:
```sql
ALTER TABLE public.sessions
  ADD COLUMN IF NOT EXISTS session_flags jsonb NOT NULL DEFAULT '{}';
```
No data migration needed (all existing rows get `{}`). No RLS change needed (sessions RLS
already covers the row; adding a column inherits the same policy).

### AC 2 — MediaPipe miss counter in Redis
Each 5-second window where `behavioral_score`, `head_pose_score`, AND `blink_rate` are ALL
`None` increments a Redis counter: `INCR session:{session_id}:mediapipe_miss_count`.
The counter has a TTL of 20 s (covers the 3-window, 15-second consecutive window; resets
automatically if any MediaPipe signal arrives before the TTL expires).

### AC 3 — 3-miss alert fires once per session
When the counter reaches 3 AND `session_flags.mediapipe_limited` is not already `true`:
1. WebSocket sends a `{"type": "camera_failure_alert", "detail": "MediaPipe tracking unavailable"}` message to the client.
2. `sessions.session_flags` is updated via `UPDATE sessions SET session_flags = session_flags || '{"mediapipe_limited": true}'::jsonb WHERE session_id = $1`.
3. Redis key `session:{session_id}:mediapipe_alerted` is set (value `"1"`, no TTL) to prevent re-alerting on subsequent windows.

### AC 4 — Redistribution is automatic (no special casing)
No special code is needed in `process_attention_signal` to handle the `mediapipe_limited`
state. The redistribution already happens correctly in `compute_ces` when the three fields
are `None` (via Story 3-34 + Story 3-38). AC 4 is a verification criterion, not a code
requirement: confirm with a unit test that `compute_ces(behavioral=None, head_pose=None,
blink=None, quiz_accuracy=0.8, teachback_score=None, settings=s)` produces the expected
redistribution result.

### AC 5 — Miss counter resets when MediaPipe recovers
When any window arrives with at least one non-None MediaPipe signal, `DEL session:{session_id}:mediapipe_miss_count` is called. (The alerted flag `mediapipe_alerted` is NOT reset — the alert fires once per session even if MediaPipe recovers.)

### AC 6 — Alert write is non-blocking
The `UPDATE sessions SET session_flags = ...` and the WebSocket send are best-effort.
A DB write failure does not drop the CES computation or WebSocket message.

### AC 7 — No ruff errors

### AC 8 — Unit tests: 18 minimum
At minimum 18 unit tests: 2-miss counter (no alert), 3-miss counter (alert fires),
4th miss (no re-alert — already_alerted guard), recovery (counter deleted on non-None signal),
session_flags UPDATE payload verified, WebSocket camera_failure_alert message shape,
redistribution verification (AC 4 assertion), idempotent alert (calling twice does nothing).

---

## Tasks / Subtasks

- [ ] **T1** Write the migration file `supabase/migrations/20260811000000_session_flags.sql`
- [ ] **T2** Write RED tests
- [ ] **T3** Implement miss counter logic in `process_attention_signal` (Dev 4 code — coordinate):
  - After parsing signal, if all 3 MediaPipe fields None: `INCR` + `EXPIRE 20` on miss counter
  - If any MediaPipe field non-None: `DEL` miss counter
  - If miss counter >= 3 AND `mediapipe_alerted` key absent: trigger alert
- [ ] **T4** Implement `trigger_mediapipe_alert(session_id, supabase, websocket_manager)` helper in `assessment/service.py`
- [ ] **T5** Run `ruff check` + `pytest -m unit` — all pass
- [ ] **T6** 6-agent adversarial code review

---

## Scale & Load

**Q1 — Unit of work and range:**
One Redis INCR + EXPIRE per window where all 3 MediaPipe fields absent. One Redis DEL per
window where any MediaPipe field present. Maximum: 1 INCR + 1 EXPIRE per 5 s per session.
One DB UPDATE (session_flags) per session (at most once, per the alerted flag guard).

**Q2 — Fixed budgets vs variable input:**
The miss counter has a 20 s TTL — capped at approximately 4 increments max before expiry
resets it. The alert fires at most once per session (enforced by `mediapipe_alerted` Redis
key, no TTL). `session_flags` JSONB column has no size limit from PostgreSQL's perspective;
the values stored are small, bounded JSON objects.

**Q3 — Scope of every limit:**
Per-session. Redis keys `session:{session_id}:mediapipe_miss_count` and
`session:{session_id}:mediapipe_alerted` are scoped to the session. DB UPDATE targets
exactly one sessions row.

**Q4 — Unbounded reads/writes:**
The DB UPDATE `session_flags = session_flags || '...'::jsonb` is a single row operation
bounded by session scope. Redis INCR and EXPIRE are O(1). No unbounded reads.

**Q5 — Inherited caps re-derived:**
"3 consecutive windows" = 15 s of no camera signal. Re-derived: 3 was chosen as the minimum
sample to distinguish a transient hiccup (1–2 windows) from a genuine failure (3+). The
20 s TTL covers the 15 s window with a 5 s grace buffer. These values are not configurable
in this story (hardcoded constants) but can be made env vars in a calibration story if
real-student data shows different rates.

**Q6 — Check-then-act under concurrency:**
Two concurrent WebSocket messages for the same session both incrementing the miss counter
is safe — Redis INCR is atomic. The alert trigger check (`mediapipe_alerted` key absent)
is a check-then-act: two concurrent processes could both see the key absent and both fire
the alert. Guard with `SET session:{session_id}:mediapipe_alerted 1 NX` (SET if Not eXists)
— the NX flag ensures only one writer succeeds, and the losing writer skips the alert.

---

## Definition of Done

- [ ] Migration file created (NOT applied — user applies to Supabase)
- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN (minimum 18 unit tests)
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed
- [ ] `docs/dev3-assessment-tracker.md` updated
- [ ] PR merged to main

---

## Dev Notes

### Migration

```sql
-- supabase/migrations/20260811000000_session_flags.sql

-- Add session_flags JSONB to sessions table (S3-39: MediaPipe failure protocol)
-- All existing rows receive default '{}' — no data migration required.
-- RLS unchanged: sessions RLS covers rows by user_id; column inherits the policy.

ALTER TABLE public.sessions
  ADD COLUMN IF NOT EXISTS session_flags jsonb NOT NULL DEFAULT '{}';

COMMENT ON COLUMN public.sessions.session_flags IS
  'Per-session runtime flags: mediapipe_limited, partial_session, etc.';
```

**DO NOT apply this migration directly** — create the file and have the team PR it. The user
applies it via Supabase dashboard or CLI after review.

### Alert trigger helper (Dev 3 scope)

```python
# apps/api/app/modules/assessment/service.py

async def trigger_mediapipe_alert(
    session_id: str,
    *,
    supabase,
    ws_manager,
) -> None:
    """Write mediapipe_limited flag and notify client. Fire-and-forget safe."""
    await supabase.table("sessions").update({
        "session_flags": {"mediapipe_limited": True},  # JSONB merge via || in SQL
    }).eq("session_id", session_id).execute()

    await ws_manager.send_personal_message(
        {"type": "camera_failure_alert", "detail": "MediaPipe tracking unavailable"},
        session_id=session_id,
    )
```

Note: Supabase Python client does not natively support JSONB `||` merge in UPDATE. Use raw
SQL via `.rpc()` or restructure to `session_flags = jsonb_set(session_flags, ...)`.
Preferred pattern: `await supabase.rpc("merge_session_flag", {"p_session_id": session_id, "p_key": "mediapipe_limited", "p_value": True}).execute()`.

### Miss counter logic (Dev 4 scope in process_attention_signal)

```python
miss_key = f"session:{session_id}:mediapipe_miss_count"
alerted_key = f"session:{session_id}:mediapipe_alerted"

all_mediapipe_none = (
    signal.behavioral_score is None and
    signal.head_pose_score is None and
    signal.blink_rate is None
)

if all_mediapipe_none:
    count = await redis.incr(miss_key)
    await redis.expire(miss_key, 20)
    alerted = await redis.get(alerted_key)
    if count >= 3 and alerted is None:
        # NX guard — only one concurrent writer proceeds
        set_ok = await redis.set(alerted_key, "1", nx=True)
        if set_ok:
            asyncio.create_task(trigger_mediapipe_alert(session_id, supabase=supabase, ws_manager=manager))
else:
    await redis.delete(miss_key)
```

### Files to create/modify

- `supabase/migrations/20260811000000_session_flags.sql` — new migration (do NOT apply)
- `apps/api/app/modules/assessment/service.py` — add `trigger_mediapipe_alert()`
- `apps/api/app/modules/tutor/service.py` — Dev 4 adds miss counter logic
- `apps/api/tests/test_mediapipe_failure_protocol.py` — new test file
