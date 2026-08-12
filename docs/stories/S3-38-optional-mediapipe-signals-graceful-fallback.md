---
id: "S3-38"
title: "Make behavioral_score, head_pose_score, blink_rate Optional in NormalizedSignal (D13)"
status: "Draft"
sprint: 3
story_points: 2
owner: Dev4
decisions: [D13]
depends_on: []
branch: sprint3/s3-38-optional-mediapipe-signals
migration: "NO"
---

# Story S3-38 — Optional MediaPipe Signals

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 4
**Status:** Draft
**Branch:** `sprint3/s3-38-optional-mediapipe-signals`
**Decisions covered:** D13
**Migration:** NO

---

## User Story

**As the CES signal processor**,
**I want** `behavioral_score`, `head_pose_score`, and `blink_rate` to be `float | None`
in `NormalizedSignal` and parsed via `_optional_float`,
**so that** a MediaPipe frame drop (which sends `null` for those fields) is handled
gracefully rather than raising a `ValueError` that crashes the attention signal path.

---

## Background

`_parse_signal` currently calls `_require_float("behavioral_score")` etc., which raises
`ValueError` if the field is absent or null. A MediaPipe frame drop (e.g., face not
visible) sends `null` for behavioral, head_pose, and blink signals. This means any
frame drop currently crashes `process_attention_signal` and delivers a 422 error to
the WebSocket client.

`compute_ces` in `tutor/service.py` already handles `None` signals via proportional
weight redistribution (the general form of the PRD §11 teachback-None rule). Making
these fields Optional merely unlocks that existing redistribution path.

---

## Acceptance Criteria

### AC 1 — `NormalizedSignal` fields are Optional
`behavioral_score: float | None`, `head_pose_score: float | None`, `blink_rate: float | None`.

### AC 2 — `_parse_signal` uses `_optional_float` for these three fields
No `_require_float` call for behavioral, head_pose, blink.

### AC 3 — `null` payload fields produce None in NormalizedSignal (no ValueError)
`_parse_signal({"session_id": "x", "behavioral_score": None, "head_pose_score": None,
"blink_rate": None, "quiz_accuracy": None, "teachback_score": None})` must not raise.

### AC 4 — `compute_ces` redistributes weights when behavioral/head_pose/blink are None
`compute_ces` output when only quiz=0.5 is present equals `0.5 * 100 = 50.0` (full
redistribution to single present signal). Existing S3-34 tests verify this.

### AC 5 — All existing tests remain GREEN
No regressions in tutor service test suite.

---

## Tasks

- [ ] Change `behavioral_score: float | None` in `NormalizedSignal`
- [ ] Change `head_pose_score: float | None` in `NormalizedSignal`
- [ ] Change `blink_rate: float | None` in `NormalizedSignal`
- [ ] Replace `_require_float("behavioral_score")` with `_optional_float("behavioral_score")`
- [ ] Replace `_require_float("head_pose_score")` with `_optional_float("head_pose_score")`
- [ ] Replace `_require_float("blink_rate")` with `_optional_float("blink_rate")`
- [ ] Write 3 RED tests (AC1–AC3), run GREEN
- [ ] Run full regression suite

---

## Scale & Load

1. **One unit of work:** One signal parse per WebSocket message (~every 5s per session).
   Range: 0–∞ (one per CES window, capped by session TTL).
2. **Fixed budgets vs variable input:** None introduced. `_optional_float` path has
   the same compute cost as `_require_float` (field lookup + float cast).
3. **Scope:** Per session, per signal window.
4. **Unbounded reads/writes:** None. Pure in-memory parsing.
5. **Inherited caps re-derived:** N/A.
6. **Concurrent safety:** `_parse_signal` is a pure function, thread-safe.
