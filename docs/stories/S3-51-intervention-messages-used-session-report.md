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

### AC 1 — `intervention_messages_used: int` on `SessionReport`
New integer field, default 0, always present.

### AC 2 — Value equals count of `intervention_triggered` events for the session
Same source as `interventions_count` — the `session_events` table query.

### AC 3 — 0 when no interventions occurred

---

## Scale & Load

1. **Unit:** One `count=exact` query on session_events per session report call.
2. **Budgets:** Bounded by `max_distraction_per_session=3` + 1 fatigue = max 4 per session.
3. **Scope:** Per session.
4. **Unbounded:** None — filter on session_id + event_type is naturally bounded.
5. **Inherited caps:** N/A.
6. **Concurrent:** Read-only; no TOCTOU risk.
