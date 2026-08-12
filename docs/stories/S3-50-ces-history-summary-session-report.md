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

### AC 1 — `ces_history_summary: dict[str, Any] | None = None` on `SessionReport`
Field is present in the Pydantic model with default `None` and type
`dict[str, Any] | None`. Verified via `SessionReport.model_fields`.

### AC 2 — Dict contains exactly `{mean, min, max, window_count}` from Redis ces_history
Populated from `session:{id}:ces_history` JSON entries (`{"v": float, "t": int}`).
Keys: `mean: float`, `min: float`, `max: float`, `window_count: int`.
No other keys. Backward-compat: bare-float legacy entries (pre-S3-49) accepted via fallback.

### AC 3 — `None` when redis is None OR when history returns empty list
Two paths: (a) `redis` kwarg not provided — guard is `if redis is None`; (b) redis provided
but `lrange` returns `[]` — guard is `if ces_vals:`. Both produce `None`, no crash.

### AC 4 — mean/min/max rounded to 2 decimal places; window_count is int (no rounding)

### AC 5 — At least 5 tests covering AC 1–4 (minimum test count gate)
- Model field presence (AC 1)
- Service computes correct mean/min/max/window_count from 3 entries (AC 2)
- None when redis=None (model-level, AC 3a)
- None when redis provided but history empty (service-level, AC 3b)
- Values rounded to 2dp with irrational inputs (AC 4)

---

## Scale & Load

1. **Unit:** One `get_session_report` call per session end. Within it, one `redis.lrange`
   call reads `session:{id}:ces_history`. Min: 0 entries (first-window race / cold start).
   Typical: 5–18 entries (90-min session at 5-s cadence, capped at 10 by ltrim).
   Largest measured: 10 (hard cap via ltrim, S3-34). Beyond cap: ltrim prevents
   any entry exceeding 10; excess entries are silently dropped at write time (design intent,
   not silent truncation — the cap was derived for this use case in S3-34 and re-confirmed
   at S3-49 JSON format migration).

2. **Budgets (FIXED while input VARIES):** `_CES_HISTORY_MAX = 10`. The read at
   `lrange(0, _CES_HISTORY_MAX - 1)` is self-enforced at the read site (as of the S3-50
   audit fix) and also enforced at write via `ltrim`. Past the 10-entry budget: the oldest
   entries are silently dropped. This is explicit design — the summary reflects the most
   recent 10 windows, not the full session. Empty list → `ces_history_summary = None`
   (no silent zero). Fewer than 10 entries → valid summary computed from whatever is present.

3. **Scope:** Per session. Redis key scoped to `session:{id}:ces_history`. Multiple
   instances share Railway Redis — no scope ambiguity; all instances read the same key.

4. **Unbounded reads:** None. `lrange(0, 9)` reads at most 10 bytes-sized JSON strings
   (~35 bytes each = 350 bytes max). No rows materialised from Supabase for this step.

5. **Inherited caps:** `_CES_HISTORY_MAX = 10` was set in S3-34 for bare-float entries.
   Re-derived at S3-49 (JSON format, ~35 bytes/entry vs ~10 bytes — still trivially bounded
   at 350 bytes). Re-confirmed here: 10 windows is sufficient to detect engagement trend
   (mean/min/max) and more than sufficient for the 2-window distraction trigger.

6. **Concurrent safety:** Read-only. `get_session_report` is called after session end.
   No write race. Multiple concurrent report requests for the same session see the same
   Redis key — idempotent read, no TOCTOU risk.
