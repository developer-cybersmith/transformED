---
id: "S3-42"
title: "Per-signal Redis histories for accurate CES breakdown in session report (D9)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev4
decisions: [D9]
depends_on: [S3-38, S3-39]
branch: sprint3/s3-42-per-signal-history
migration: "NO"
---

# Story S3-42 — Per-Signal Redis Histories (CES Breakdown Accuracy)

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 4
**Status:** Draft
**Decisions covered:** D9
**Migration:** NO — uses existing Redis keys; no schema changes

---

## User Story

**As the session report system**,
**I want** `get_session_report` to read real per-signal averages (behavioral, head_pose, blink)
from Redis histories instead of using `0.0` placeholders,
**so that** `SessionReport.ces_breakdown` accurately reflects the student's engagement signals
rather than always showing zero for the behavioral/head_pose/blink components.

---

## Background

`_build_ces_breakdown` in `assessment/service.py` currently passes `0.0` for `behavioral_avg`,
`head_pose_avg`, and `blink_avg` (marked with comment "S3-42 not yet implemented").

The fix has two parts:
1. `process_attention_signal` (tutor/service.py) must write per-signal values into bounded
   Redis lists (`session:{id}:behavioral_history`, etc.) alongside the `ces_history` write it
   already does.
2. `get_session_report` must accept an optional `redis` client, read those histories via a
   `_signal_avg` helper, and pass real averages to `_build_ces_breakdown`.

---

## Acceptance Criteria

### AC 1 — Per-signal history written on each TEACHING-state window
`process_attention_signal`, when `state_raw == "TEACHING"`, writes each non-None signal value
to its Redis list:
- `session:{id}:behavioral_history` (only when `behavioral_score` is not None)
- `session:{id}:head_pose_history` (only when `head_pose_score` is not None)
- `session:{id}:blink_history` (only when `blink_rate` is not None)

Each list is trimmed to at most `_CES_HISTORY_MAX` (10) entries via `ltrim`.

### AC 2 — None signals do not write to their history
If `normalized.behavioral_score is None`, no write to `behavioral_history` occurs.
Same for `head_pose_score` and `blink_rate`.

### AC 3 — `get_session_report` accepts optional `redis` parameter
`get_session_report(*, session_id, user_id, supabase, redis=None)` — backward compatible.

### AC 4 — `_signal_avg` reads from Redis histories
When `redis` is provided, `get_session_report` reads each per-signal history (lrange 0..9,
bounded), converts to floats, averages them, and passes to `_build_ces_breakdown`.

### AC 5 — Graceful fallback when `redis` is None or history is empty
If `redis` is None, or a history key is empty, the corresponding average defaults to `0.0`.
No crash, no HTTP error.

### AC 6 — Router passes `redis=get_redis()` to `get_session_report`
`get_session_report_endpoint` in `router.py` imports `get_redis` and passes it.

### AC 7 — ces_breakdown behavioral/head_pose/blink are non-zero when histories have data
Integration: after a TEACHING-state window with non-None signals, `ces_breakdown.behavioral`
is > 0.0 (was always 0.0 before this story).

---

## Tasks

- [x] Add per-signal lpush/ltrim to `process_attention_signal` in `tutor/service.py`
- [x] Add `redis: Any = None` to `get_session_report` signature
- [x] Add `_signal_avg` closure inside `get_session_report` to read Redis histories
- [x] Pass real signal averages to `_build_ces_breakdown`
- [x] Update router call site to pass `redis=get_redis()`
- [x] Write RED tests (AC1–AC7)
- [x] Run full test suite GREEN

---

## Scale & Load

1. **One unit of work:** Three additional `lpush` + `ltrim` calls per TEACHING-state window.
   Range: at most 3 writes per attention signal (~every 5s during TEACHING). Each list capped
   at 10 entries — reads for the report are always `lrange 0..9`, bounded at write time.
2. **Fixed budgets:** Each history list capped at `_CES_HISTORY_MAX=10` entries via `ltrim`.
   Past that limit, old entries are dropped. The 0.0 fallback (AC5) handles the empty-list case
   explicitly — no silent truncation.
3. **Scope:** Per session. Three Redis list keys per session. TTL inherited from the existing
   `_CES_WINDOW_TTL=86400s` pattern (the ltrim enforces count; no explicit `expire` added here
   since these keys live and die with the session Redis data).
4. **Unbounded reads/writes:** None. `lpush + ltrim` is O(1) amortised. `lrange 0..9` is O(10).
5. **Inherited caps re-derived:** `_CES_HISTORY_MAX=10` was set for `ces_history`; the same cap
   is reused for per-signal histories. A 5-second cadence over a 60-min session = 720 windows;
   ltrim keeps only the last 10 — the average covers the most recent engagement window only.
   This is intentional (recency bias) and matches the existing ces_history behaviour.
6. **Concurrent safety:** Redis `lpush + ltrim` is not atomic as a pair but the race is benign:
   the worst outcome is an 11-item list for one window — the report `lrange 0..9` still reads
   at most 10 entries. No TOCTOU risk: histories are append-only, never conditionally written.
