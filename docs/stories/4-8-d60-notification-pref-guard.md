---
status: in-progress
---

# Story 4-8 — D60 Notification Preference Guard: Wire `get_notification_preference()` into Session Report Email Delivery

**Sprint:** 4 · **Owner:** Dev 3  
**Branch:** `sprint4/s4-8-d60-notification-pref`  
**Defect:** D60 (Sprint 3 renumbered — `user_notification_preferences` table + notification guard)

## User Story

As a student who has opted out of session report emails, I want the system to respect my preference so that I do not receive emails I have declined.

## Background

`get_notification_preference()` is fully implemented in `apps/api/app/modules/assessment/notification_prefs.py` (Story 3-33, 2026-08-06). The `user_notification_preferences` table is applied via migration `20260806000000_user_notification_preferences.sql` (Dev 1, 2026-08-06). Dev 4's PATCH endpoint (`/api/users/notifications`) is also complete.

**The missing piece (D60 Dev 3 portion):** no email delivery function exists to wire the guard into. The locked technology stack (CLAUDE.md) names no email provider. This story creates `send_session_report_email()` — a guarded stub that:
1. Checks the preference gate immediately
2. Returns early if opted out (guard is active now)
3. Logs "provider not configured" if opted in (no actual send — placeholder for Sprint 5+)

This closes D60's Dev 3 responsibility. When an email provider is added, the guard is already there and the provider just needs to replace the log statement.

## Acceptance Criteria

- **AC1:** `apps/api/app/modules/assessment/email_delivery.py` created with `send_session_report_email(*, user_id, session_id, supabase)` as its single public export
- **AC2:** Function calls `get_notification_preference(user_id, "session_report_email", supabase)` as its FIRST action before any other logic
- **AC3:** If preference returns `False`: function returns immediately, logs opt-out notice at INFO level — no send path reached
- **AC4:** If preference returns `True` (or `True` via fail-open): function logs "provider not configured" and returns — send path stubbed
- **AC5:** If `get_notification_preference` raises any exception: exception is NOT caught inside `send_session_report_email` — it propagates so callers know the preference check failed (distinct from the fail-open behaviour inside `get_notification_preference` itself, which never raises)
- **AC6:** Three unit tests cover: opted-out (AC3), opted-in stub (AC4), and that preference is called before the send branch in all paths (AC2)
- **AC7:** `docs/DEFECT-REGISTER.md` — D60 Dev 3 portion closed with enforcement note
- **AC8:** `docs/dev3-assessment-tracker.md` — S4-8 marked done, dashboard updated

## Scale & Load

1. **Unit of work:** One preference DB read per email send attempt. Row count: 1 (`user_notification_preferences` keyed by `user_id`). Fixed cost regardless of session length.
2. **Fixed budgets while input varies:** N/A — the guard is a single `.maybe_single()` query; no fan-out.
3. **Scope of each limit:** Per user. One row per user in `user_notification_preferences`; RLS enforces ownership.
4. **Unbounded reads/writes:** None. The query is `SELECT session_report_email FROM user_notification_preferences WHERE user_id = $1` — single-row lookup, always bounded.
5. **Inherited caps re-derived:** N/A — no inherited limits. The `get_notification_preference` helper already has the `.maybe_single()` pattern which returns at most one row.
6. **Concurrent check-then-act:** The guard is read-only. Race condition does not apply — even if preference changes between read and send, the worst outcome is one extra email to a user who just opted out (acceptable; no data loss or duplication).

## Tasks

- [x] T1: Create story file (this file), commit alone, push
- [ ] T2: Write `apps/api/app/modules/assessment/email_delivery.py` with guarded stub
- [ ] T3: Write `apps/api/tests/test_d60_notification_pref_guard.py` with 3+ unit tests
- [ ] T4: Run full test suite + ruff + mypy — all clean
- [ ] T5: Update `docs/DEFECT-REGISTER.md` — D60 Dev 3 portion closed
- [ ] T6: Update `docs/dev3-assessment-tracker.md` — S4-8 done, dashboard
- [ ] T7: Commit implementation, push, open PR into `master-sprint4-dev3`

## Change Log

| Date | Author | Change |
|---|---|---|
| 2026-08-31 | Dev 3 | Story file created |
