---
baseline_commit: 1884f2b
---

# Story 2.43: Notifications UI — Wire to Real Backend (S3-07)

Status: draft

## Story

As a student,
I want my notification preference toggles (session report, lesson ready, weekly progress, streak reminders) to actually persist,
so that my choices survive a page reload and the platform genuinely respects them, instead of silently resetting on every refresh.

**Source:** `docs/DEFECT-REGISTER.md` D60 — "S3-07 (Notifications UI) has three missing infrastructure pieces." All three backend pieces are now closed: Dev 3 (Story 3-33, read-helper), Dev 1 (migration `20260806000000_user_notification_preferences.sql`), Dev 4 (Story 4-23, `PATCH /api/auth/notifications`, 16 tests green, merged to `main` via PR #128, commit `1884f2b`). This story is the fourth and final piece: **Dev 2 — wire frontend to the real endpoint and remove the in-memory mock.**

**Real endpoint contract, verified directly against `apps/api/app/modules/auth/router.py` (not taken on faith from the cross-team announcement):**

```
PATCH /api/auth/notifications
Authorization: Bearer <jwt>

Body (all optional, at least one required — extra='forbid', unknown fields 422):
{
  "session_report_email": bool,
  "lesson_ready_email": bool,
  "weekly_progress_email": bool,
  "streak_reminders": bool
}

Response 200: { user_id, session_report_email, lesson_ready_email, weekly_progress_email, streak_reminders, updated_at }

401/403 no or invalid JWT · 422 empty body or extra fields · 503 read failure (retry) · 500 upsert failure
```

**No GET endpoint exists.** Confirmed by reading `auth/router.py` directly — there is no `@router.get(".../notifications")`. Reads happen via a direct Supabase client query against `public.user_notification_preferences` (RLS: `"select own"`, `USING (auth.uid() = user_id)`, confirmed in `supabase/migrations/20260806000000_user_notification_preferences.sql`) — the exact same own-row-read pattern already established in this codebase for `learner_dna` (`proxy.ts`) and `users.attention_consent` (`useAttentionConsent.ts`, Story 2-42). Writes go through the real `PATCH` endpoint — never a direct Supabase write — because that endpoint is the documented, tested, sole writer (Dev 4's own docstring: read-merge-upsert with TOCTOU-safe semantics via the table's `PRIMARY KEY (user_id)`).

**Current frontend state (all to be replaced, not left alongside):** `NotificationsTab.tsx` renders only 3 toggles (Lesson Ready, Weekly Progress, Streak Reminders) — missing the 4th real field, **Session Report**, entirely. Backed by `settingsService.getNotifications`/`updateNotifications` → `mocks/api/settings.ts` → an in-memory `mockUser.notifications` object that resets on every page reload. Confirmed via repo-wide search: `NotificationSettings` (type), `getNotificationSettings`, `updateNotificationSettings` are referenced only by this feature's own 5 files — safe to delete entirely rather than leave as dead code (per `docs/DEFECT-REGISTER.md` D56's own resolution guidance: delete mock plumbing as one deliberate change once nothing real depends on it, not by attrition).

## Acceptance Criteria

1. **AC-1** — `NotificationsTab.tsx` renders **4** toggles matching the real backend fields exactly: Session Report (**new** — does not exist in the UI today), Lesson Ready, Weekly Progress, Streak Reminders.
2. **AC-2** — On mount, reads the current user's `user_notification_preferences` row directly via the Supabase client (own-row, RLS-scoped — `supabase.from('user_notification_preferences').select(...).eq('user_id', user.id).maybeSingle()`). When no row exists yet (a user who has never touched a toggle — the table has no auto-create trigger), all four toggles default to `true`, matching the backend's own `_NOTIF_DEFAULTS` and the migration's column `DEFAULT true` clauses exactly — not a separately-invented frontend default.
3. **AC-3** — Toggling a preference calls the real `PATCH /api/auth/notifications` with **only that one field** (matching the endpoint's partial-update semantics — never re-sends the full merged object, which would risk clobbering a field changed by a concurrent request elsewhere). Optimistic UI update on click; rolls back to the prior value if the request fails.
4. **AC-4** — A failed update is logged via `console.error` (genuinely unexpected failure, not a normal user action — same reasoning already established in `SignInForm.tsx`/`AttentionConsentModal.tsx`) in addition to the silent rollback; no intrusive error banner is required for a settings toggle.
5. **AC-5** — **Race guard:** if a toggle is clicked again (or a different toggle is clicked) while a previous `PATCH` for the same field is still in flight, a late-arriving stale response must never overwrite a more recent optimistic value or a more recent request's result — same class of bug as Story 2-42's Accept/Decline race, guarded the same way (a per-field request-generation token).
6. **AC-6** — `user_id` is never included in the request body (the backend derives it from the JWT and would 422 on an unknown field if it were sent — this is a structural guarantee via the schema's `extra='forbid'`, not just a frontend convention to remember).
7. **AC-7** — The request body is never empty — satisfied naturally since a toggle click always changes exactly one field, but tested explicitly to guard against a future refactor that batches multiple field changes into one call incorrectly.
8. **AC-8** — All in-memory mock plumbing for notifications is deleted, not left dead: `mocks/api/settings.ts`'s `getNotificationSettings`/`updateNotificationSettings`, `mocks/data/users.ts`'s `NotificationSettings` interface and the `notifications` field off `MockUser`/`mockUser`, and `settings.service.ts`'s old mock-delegating `getNotifications`/`updateNotifications` methods.
9. **AC-9** — Tests: the hook's full state matrix (row exists with mixed true/false values; no row → all four default `true`, no log; read throws/errors → all four default `true`, WITH a logged error — matching AC-4's "log genuine failures" reasoning applied to reads too), the component's toggle/optimistic-update/rollback/race-guard behavior, and confirmation (via `git grep`, not just trusting the diff) that no other file still imports the deleted mock exports. Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions, per the BMAD Pre-Implementation Checklist (this section was missing from Story 2-42 — an oversight this story does not repeat):

1. **Unit of work and range:** one Supabase read (≤1 row, `PRIMARY KEY (user_id)`) on mount, one `PATCH` (1 field per request, never more) per toggle click. No variable-size input exists anywhere in this story — every request touches exactly one user's exactly one row.
2. **Fixed budgets vs. variable input:** N/A with reason — the request body is a fixed 4-optional-boolean shape enforced by the backend's Pydantic schema (`extra='forbid'`); there is no list, no file, no pagination for this frontend to bound.
3. **Scope of every limit:** per-user only — RLS (`auth.uid() = user_id`) on the read, JWT-derived `user_id` on the write. Nothing shared or global is touched.
4. **Unbounded reads/writes:** none. The Supabase read is a single-row `.maybeSingle()` query keyed by primary key; the backend's own write path is already documented as bounded (`test_unbounded_queries.py`-satisfying, per Dev 4's docstring).
5. **Inherited caps re-derived:** none inherited — this is new frontend code calling a freshly-built, already-scale-reviewed backend endpoint (Story 4-23's own 6-layer review covered its scale properties).
6. **Concurrent requests safe?** Backend: read-merge-upsert is last-writer-wins on truly concurrent PATCHes for *different* fields from *different* tabs — an explicitly accepted tradeoff in Dev 4's own docstring ("acceptable for preferences"), not something this story needs to re-solve. Frontend: AC-5's per-field request-generation guard is exactly this question answered for the same-field-rapid-toggle case, which the backend's concurrency story does not cover on its own (two PATCHes for the *same* field from the *same* tab, reordered in flight).

## Tasks / Subtasks

- [ ] Task 1 (AC: 2, 9): Build `useNotificationPreferences()` hook — Supabase read of `user_notification_preferences`, defaults-on-no-row, degrade-with-log on error.
  - [ ] 1.1 RED: tests for the three read-state cases (row with mixed values / no row → defaults, no log / read error → defaults, WITH log).
  - [ ] 1.2 GREEN: implement.
- [ ] Task 2 (AC: 3, 5, 6, 7): Add `updateNotifications()` to `settings.service.ts` (real `PATCH auth/notifications` call); wire the hook's update function with the per-field request-generation race guard.
  - [ ] 2.1 RED: tests that a single-field PATCH fires with no `user_id`, that a stale response can't overwrite a newer one (AC-5), and that the body is never empty.
  - [ ] 2.2 GREEN: implement.
- [ ] Task 3 (AC: 1, 4): Rewrite `NotificationsTab.tsx` — 4 toggles (add Session Report), optimistic update + rollback + console.error on failure, using the new hook instead of local `useState`/`useEffect` boilerplate.
  - [ ] 3.1 RED: tests that all 4 toggles render with real values, a toggle click calls the real service with the correct single-field payload, and a failure rolls back and logs.
  - [ ] 3.2 GREEN: implement.
- [ ] Task 4 (AC: 8): Delete the in-memory mock plumbing entirely.
  - [ ] 4.1 RED: a guard assertion (or manual `git grep`) proving no remaining reference to the deleted exports outside this story's own removed lines.
  - [ ] 4.2 GREEN: delete `mocks/api/settings.ts`'s two functions, `mocks/data/users.ts`'s `NotificationSettings` type + `MockUser.notifications` field, `settings.service.ts`'s old mock-delegating methods, and the now-obsolete old test file content.
- [ ] Task 5 (AC: 9): Full suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT write directly to `user_notification_preferences` from the frontend, even though RLS technically permits an own-row `UPDATE`/`INSERT`. The real `PATCH /api/auth/notifications` is the documented, tested, sole writer (Dev 4's own docstring calls this out explicitly) — bypassing it would duplicate the read-merge-upsert logic client-side and lose the backend's validation (extra-field rejection, at-least-one-required) entirely. This is the corrected lesson from Story 2-42's own review: build against the real write endpoint when one exists, don't reach for a client-side Supabase write just because RLS would technically allow it.
- Do NOT invent frontend-only default values for the four toggles. Use the exact same `true` defaults the backend's `_NOTIF_DEFAULTS` and the migration's column `DEFAULT` clauses already declare — a drift here (e.g. defaulting `streak_reminders` to `false` client-side) would show a student a setting that doesn't match what the backend would actually apply on their first real write.
- Do NOT batch multiple toggle changes into a single PATCH call "for efficiency" — each toggle already fires independently today, and AC-3/AC-7 depend on that shape (partial update semantics, body never empty by construction).

### Testing standards

Mock the Supabase client the same way `useAttentionConsent.test.ts` does (module-level mock of `@/lib/supabase/client`'s `createClient()`, not the network level). Mock `settingsService.updateNotifications` at the service boundary for the hook/component tests, matching how `ChapterGenerateControl.test.tsx` mocks `booksService.generateLesson`. Per `docs/DEFECT-REGISTER.md` binding rule 2, assert the actual resulting state (the toggle's rendered checked/unchecked value, not merely that a mock function was called) wherever the assertion allows it.

### References

- [Source: `docs/DEFECT-REGISTER.md` D60 — full history of all four pieces (Dev 3/Dev 1/Dev 4 closed, Dev 2 this story)]
- [Source: `apps/api/app/modules/auth/router.py:66-304` — the real `PATCH /api/auth/notifications` contract, verified directly, not from the cross-team announcement alone]
- [Source: `supabase/migrations/20260806000000_user_notification_preferences.sql` — table schema, column defaults, RLS policies]
- [Source: `apps/web/src/hooks/useAttentionConsent.ts` (Story 2-42) — the exact own-row Supabase-read pattern this story's hook reuses, including the request-generation race-guard pattern for AC-5]
- [Source: `apps/web/src/services/onboarding.service.ts` — the real-endpoint service-layer convention (`api.VERB<Type>(path, body).then(r => r.data)`) to follow for `settings.service.ts`'s new `updateNotifications`]
- [Source: `apps/web/src/components/settings/tabs/NotificationsTab.tsx` (current) — component being replaced; existing optimistic-update/rollback shape to preserve]
- [Source: `docs/DEFECT-REGISTER.md` D56 — precedent for deleting dead mock plumbing as one deliberate change, not by attrition]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Story created per S3-07 in `docs/dev2-sprint-tracker.md` / D60. Branch `sprint3/s3-07-notifications-ui` off `main` at `1884f2b`. Verified the real `PATCH /api/auth/notifications` contract directly against `apps/api/app/modules/auth/router.py` before writing any AC. | Dev 2 |

## Dev Agent Record

### Implementation Plan

_(filled in during dev-story)_

### Completion Notes

_(filled in during dev-story)_

### File List

_(filled in during dev-story)_
