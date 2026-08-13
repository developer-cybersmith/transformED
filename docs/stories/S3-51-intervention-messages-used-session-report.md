---
id: "S3-51"
title: "Add intervention_messages_used count to SessionReport (D19)"
status: "Draft"
sprint: 3
story_points: 1
owner: Dev3
decisions: [D19]
depends_on: [S3-36, S3-37]
branch: sprint3/s3-50-51-session-report-fields
migration: "NO"
---

# Story S3-51 — intervention_messages_used in SessionReport

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3
**Status:** Draft
**Decisions covered:** D19
**Migration:** NO — reads from session_events

---

## User Story

**As the dashboard**,
**I want** `SessionReport` to include `intervention_messages_used: int`
(count of intervention_triggered session events),
**so that** the report shows how many times the tutor intervened with a message
during the session.

---

## Acceptance Criteria

### AC 1 — `intervention_messages_used: int = 0` on `SessionReport`
Integer field, default 0, always present in `SessionReport.model_fields`.

### AC 2 — Value equals count of `intervention_triggered` events for the session
Source: the same `session_events` count query as `interventions_count` (Step 4 of
`get_session_report`). The field name reflects events triggered, not WS delivery
confirmations — WS delivery is best-effort (try/except) and not subtracted from the count.
This design choice is intentional: `interventions_count` and `intervention_messages_used`
share the same value. If a future story differentiates "triggered vs. delivered", that
story should introduce a new field or modify both fields' sources explicitly.

### AC 3 — 0 when no interventions occurred

### AC 4 — At least 4 tests covering AC 1–3 (minimum test count gate)
- Model field presence + default 0 (AC 1)
- Direct model construction with interventions_count=3 (AC 2, model-level)
- Service-level: interventions_count query result flows to intervention_messages_used (AC 2, service-level)
- 0 when no intervention events (AC 3)

---

## Scale & Load

1. **Unit:** One `get_session_report` call per session end. Within it, one `count=exact`
   query on `session_events` filtered by `session_id + event_type = "intervention_triggered"`.
   Min: 0 rows (no interventions). Typical: 1–3 rows (distraction cap = 3, fatigue cap = 1).
   Largest: 4 rows max (3 distraction + 1 fatigue per session by design constraints).
   Beyond natural max: the distraction Lua guard and fatigue SET-NX prevent additional rows.

2. **Budgets:** The `count=exact` query never materialises rows — only the integer count
   is returned. No row budget applies. The session_events table may accumulate many rows
   per session from other event types, but the filter (`event_type = "intervention_triggered"`)
   ensures only intervention rows are counted. Past the 4-per-session design ceiling: the
   query returns the correct count regardless; the guard that enforces the ceiling is the
   Lua/SET-NX mechanisms at write time, not this read path.

3. **Scope:** Per session (`session_id` filter). No cross-session reads. Railway Redis
   is shared across instances — the DB query is authoritative and instance-agnostic.

4. **Unbounded reads:** None. `count=exact` is a server-side COUNT(*) — no rows
   materialised. Filter columns: `session_id` (indexed), `event_type` (enum-like string).

5. **Inherited caps:** The 3-distraction + 1-fatigue ceiling is enforced at write time
   by: (a) `_can_intervene_distraction` Lua script (D6) for distraction, (b) `_can_intervene_fatigue`
   SET-NX (D7, fixed atomically in Sprint 3 audit) for fatigue. These caps have been
   re-derived: the ceiling is the sum of the two independent write-side guards.
   No additional ceiling is needed at the read side.

6. **Concurrent:** Read-only path; no TOCTOU risk. Multiple concurrent calls return the
   same count from the same DB state — idempotent.
