---
title: "Story 2-58 — Reports Index Page (BR-7)"
status: in-progress
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-58 — Reports Index Page (BR-7)

## Problem Statement

`Sidebar.tsx`'s `mainNavItems` has linked "Reports" to `/reports` since the sidebar was first
built — but only `apps/web/src/app/reports/[sessionId]/page.tsx` (a single session's report) has
ever existed. Visiting the bare `/reports` route 404s, and has done so from the beginning (user
report, 2026-09-05): there is no Next.js route handler for that exact path, and no way to reach it
except a raw URL — `/reports/[sessionId]` is only ever linked to from `Player.tsx`'s "Lesson
complete" screen, immediately after finishing a session, using that session's own in-memory
`sessionId`. Once a student navigates away, there is no way back to any past report at all.

There is also no backend endpoint to list a user's own past sessions — `GET
/assessment/session/{session_id}/report` (Story 3-19) only ever returns one session's data, and no
`sessions`-table read anywhere in the codebase is scoped to "all of this user's sessions." Closing
the 404 for real (not just redirecting the link away) requires a new backend endpoint plus a new
frontend index page — full-stack scope, confirmed with the user (2026-09-05) rather than assumed.

## Acceptance Criteria

- **AC1** — New `GET /assessment/sessions` endpoint (plural, matching the existing
  `POST /sessions` create route's own naming) returns the current user's own sessions, most recent
  first, each with enough context to render a list card without a second round-trip: lesson title,
  tier label, start/end timestamps, completion state, and final CES score when available.
- **AC2** — The query is bounded (`.limit()`) and scoped to the caller's own `user_id` — never
  another user's rows, never every row in the table. Passes the existing
  `tests/unit/test_unbounded_queries.py` guard with no new `_KNOWN_UNBOUNDED` entry and no
  `# BOUNDED:` escape hatch (a real `.limit()` is used, not a justified exemption).
- **AC3** — `apps/web/src/app/reports/page.tsx` (new) renders the list: each entry links to the
  existing `/reports/{session_id}` page (unchanged). An empty list (no sessions yet) shows a
  friendly empty state with a link to `/dashboard`, not a blank page. A fetch failure shows a
  graceful error state, not an unhandled crash.
- **AC4** — `Sidebar.tsx`'s existing "Reports" nav link needs no change — it already points at
  `/reports`; this story makes that path resolve instead of 404ing.
- **AC5** — New tests: backend (`apps/api/tests/unit/test_list_sessions_endpoint.py`) covering
  ownership scoping (never another user's session), the row cap, and the response shape; frontend
  (`apps/web/src/__tests__/app/reports/page.test.tsx`) covering the list render, empty state, and
  error state. `existing guard tests for assessment/router.py and assessment/service.py pass`
  (CLAUDE.md guard-test rule for touching a guarded module).
- **AC6** — `ruff check`/`ruff format --check` clean on touched Python; `tsc --noEmit` clean on
  touched TypeScript; full backend and frontend suites green, zero regressions.

## Scale & Load

1. **Unit of work / range**: one row = one `sessions` record for the calling user. A student
   creates one session per lesson attempt (Story 2-35/D18 — every "start lesson" call mints a new
   row, replays included), so this grows monotonically with usage. Min 0 (new user), typical
   single-digit-to-low-tens over a few weeks, unbounded over the lifetime of an active account —
   no real measured maximum exists yet (product has no long-lived real users), so the endpoint must
   not assume a small number.
2. **Fixed budgets vs variable input**: `.limit(50)` on the list query — a fixed cap meeting a
   variable per-user session count. Past 50, older sessions simply do not appear in this list.
   This is an **explicit, surfaced degradation**, not silent truncation: every individual session's
   own report page (`/reports/{session_id}`) remains reachable and correct regardless of list
   position — a session merely aging out of the *recent* list is not the same defect class as
   `structure_max_sections` silently cutting book content the lesson claims to cover. If real usage
   later shows students needing older history, the fix is pagination (`.range()` + a `cursor`/`page`
   param), not raising the constant.
3. **Scope of the limit**: per user, per request — the `.limit(50)` caps rows returned to *one*
   caller on *one* call; it is not a global or per-instance cap, and does not interact with any
   other user's data (RLS-equivalent `.eq("user_id", ...)` filter applied explicitly, since
   `get_supabase()` uses the service-role key and bypasses real RLS — same pattern
   `get_session_report`'s own ownership check already uses).
4. **Unbounded reads/writes**: none introduced. This story's own new query is the one read in
   question, and it is bounded per AC2. No write path is added.
5. **Inherited caps re-derived**: 50 was chosen independently, not copied from
   `dashboard.service.ts`'s existing `content/lessons` list (`limit: 20`) — that endpoint's unit of
   work is a *lesson* (a book chapter, generated once, re-generation aside), this one's is a
   *session* (one per lesson attempt, and a student may reasonably retake the same lesson several
   times), so the two caps answer different questions and must not silently inherit one number from
   the other.
6. **Concurrent safety**: read-only endpoint, no check-then-act sequence, no write, no race
   condition possible.

## Dev Notes

- Real schema, verified against migrations before writing any query (per binding rule 4):
  `public.sessions` (`supabase/migrations/20260611000000_initial_schema.sql`) — `session_id`,
  `user_id`, `lesson_id`, `ces_final`, `started_at`, `ended_at`. `public.lessons` — `title`, and
  `tier` (added later, `supabase/migrations/20260714020000_add_lesson_tier.sql`).
  `sessions.lesson_id` is a real FK to `lessons.lesson_id`.
- PostgREST embedded-resource select (`sessions.select("..., lessons(title, tier)")`) is an
  established pattern in this codebase, not a new technique —
  `apps/api/app/modules/admin/router.py` already does `.select("*, lessons(user_id)")` and parses
  the embed as a plain dict (`row.get("lessons") or {}`, `_job_row_to_summary`) since this is a
  many-to-one FK (one session → exactly one lesson) — the embed comes back as an object, not a
  list. This story's own row-mapping helper follows the identical shape.
- Ownership check follows `get_session_report`'s own established pattern
  (`apps/api/app/modules/assessment/service.py:1114`): explicit `.eq("user_id", user_id)` in the
  query itself (never trust RLS alone, since the server-side client uses the service-role key and
  bypasses it) rather than a separate post-fetch check.
- `_TIER_LABELS` (`service.py:105`) is reused for the tier label, not re-declared.
- Frontend: new `SessionSummary` type + `listSessions()` added to `apps/web/src/lib/assessment.ts`
  (same file as `getSessionReport`, same real-backend-contract convention) and
  `apps/web/src/types/assessment.ts` (the frozen OpenAPI-mirroring contract file). New
  `useSessionReports()` hook mirrors `useSessionReport.ts`'s existing SWR pattern
  (`shouldRetryOnError: false` — a 404/empty list is a real answer, not a transient failure to
  retry).

## References

- [Source: apps/web/src/components/dashboard/shell/Sidebar.tsx:16] — the pre-existing, previously
  dead `/reports` nav link this story makes resolve
- [Source: apps/web/src/components/player/Player.tsx:356-364] — the only existing way to reach
  `/reports/[sessionId]`, unchanged by this story
- [Source: apps/api/app/modules/assessment/service.py:1114] — `get_session_report`'s ownership-check
  and tier-lookup pattern, reused here
- [Source: apps/api/app/modules/admin/router.py:109,168-177] — the embedded-resource `lessons(...)`
  select pattern this story's list query follows
- [Source: apps/web/src/hooks/useSessionReport.ts] — the SWR hook pattern this story's list hook
  mirrors
- [Source: docs/SCALE-CONTRACT.md] — the six questions answered above
