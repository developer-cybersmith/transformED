---
id: "S3-50"
title: "Add ces_history_summary field to SessionReport (D18)"
status: "Draft"
sprint: 3
story_points: 2
owner: Dev3
decisions: [D18]
depends_on: [S3-35, S3-42]
branch: sprint3/s3-50-51-session-report-fields
migration: "NO"
---

# Story S3-50 — ces_history_summary in SessionReport

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3
**Status:** Draft
**Decisions covered:** D18
**Migration:** NO — reads from Redis ces_history

---

## User Story

**As the dashboard**,
**I want** `SessionReport` to include a `ces_history_summary` field with min/max/mean/window_count
computed from the Redis ces_history,
**so that** the frontend can display a compact engagement trend without requesting the raw history.

---

## Acceptance Criteria

### AC 1 — `ces_history_summary` field on `SessionReport`
`SessionReport.ces_history_summary: dict[str, Any] | None = None` — optional, backward-compatible.

### AC 2 — Field populated from Redis ces_history when redis is provided
`{mean: float, min: float, max: float, window_count: int}` computed from
`session:{id}:ces_history` JSON entries (`{"v": float, "t": int}`).

### AC 3 — None when redis is None or history empty
Graceful fallback — no crash.

### AC 4 — Values are rounded to 2 decimal places

---

## Scale & Load

1. **Unit:** One `lrange 0..9` (bounded at write by ltrim) per session report call.
2. **Budgets:** At most 10 entries read (capped by ces_history ltrim). Empty list → None.
3. **Scope:** Per session.
4. **Unbounded:** None — lrange is bounded.
5. **Inherited caps:** ces_history max 10 — same cap as _finalize_session.
6. **Concurrent:** Read-only path; no TOCTOU risk.
