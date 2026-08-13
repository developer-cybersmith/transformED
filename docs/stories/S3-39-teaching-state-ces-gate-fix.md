---
id: "S3-39"
title: "Gate compute_ces and history writes on TEACHING state (D14 — fix partial)"
status: "Draft"
sprint: 3
story_points: 1
owner: Dev4
decisions: [D14]
depends_on: []
branch: sprint3/s3-39-teaching-state-ces-gate
migration: "NO"
---

# Story S3-39 — TEACHING State CES Gate Fix

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 4
**Status:** Draft
**Decisions covered:** D14
**Migration:** NO

---

## User Story

**As the CES system**,
**I want** `compute_ces`, history writes (lpush/ltrim), and the history read to execute
ONLY when the tutor state is `TEACHING`,
**so that** CES history does not accumulate across non-TEACHING states
(QUIZZING, INTERVENING, TEACH_BACK, etc.), which would trigger false interventions.

---

## Background (Partial-fix audit finding)

`process_attention_signal` currently:
1. Reads `state_raw = await redis.get(f"tutor_state:{session_id}")` after the CES writes
2. Guards intervention dispatch on `state_raw == "TEACHING"` (correct)

But steps 1–4 (compute_ces, lpush, ltrim, lrange) run unconditionally — CES history
accumulates in ALL states, not just TEACHING. The dispatch gate is too late: history
already has values from QUIZZING/INTERVENING states that could form a false low-CES pair.

---

## Acceptance Criteria

### AC 1 — `state_raw` is read BEFORE `compute_ces`
`state_raw = await redis.get(...)` must appear before `normalized = _parse_signal(signal)`.

### AC 2 — `compute_ces`, history writes, and history read are inside `if state_raw == "TEACHING"`
When state is QUIZZING or INTERVENING, no CES computation or history update occurs.

### AC 3 — QUIZZING deadline check is preserved
The `_quiz_deadline_expired` block remains at the end, still gated on `state_raw == "QUIZZING"`.

### AC 4 — All existing tests GREEN (no regressions)

---

## Tasks

- [ ] Move state read to top of process_attention_signal (before parse/compute)
- [ ] Wrap compute_ces + Redis writes + history check inside `if state_raw == "TEACHING"`
- [ ] Write 2 RED tests confirming QUIZZING state skips CES computation
- [ ] Run full test suite GREEN

---

## Scale & Load

1. **One unit of work:** One signal window per session (~5s cadence). No change in volume.
2. **Fixed budgets:** None introduced.
3. **Scope:** Per session.
4. **Unbounded reads/writes:** None. This reduces writes (skips them in non-TEACHING states).
5. **Inherited caps:** N/A.
6. **Concurrent safety:** `state_raw` is a single atomic Redis GET. Safe under concurrent signals.
