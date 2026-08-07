---
baseline_commit: 1884f2b
---

# Story 2.43: Notifications UI — Wire to Real Backend (S3-07)

Status: done

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

**No GET endpoint exists.** Confirmed by reading `auth/router.py` directly — there is no `@router.get(".../notifications")`. Reads happen via a direct Supabase client query against `public.user_notification_preferences` (RLS: `"select own"`, `USING (auth.uid() = user_id)`, confirmed in `supabase/migrations/20260806000000_user_notification_preferences.sql`) — the exact same own-row-read pattern already established in this codebase for `learner_dna` (`proxy.ts`). Writes go through the real `PATCH` endpoint — never a direct Supabase write — because that endpoint is the documented, tested, sole writer (Dev 4's own docstring: read-merge-upsert with TOCTOU-safe semantics via the table's `PRIMARY KEY (user_id)`).

> **Correction, 2026-08-06 code review:** an earlier draft of this story claimed `useAttentionConsent.ts` (Story 2-42) as an in-branch precedent for this read pattern and the race-guard design. The Acceptance Auditor verified that claim is false as written: this branch forked from `main`, which has never contained that file — it exists only on the separate, unmerged `sprint3-master`/`sprint3/s3-01-*` branches. The design itself (own-row Supabase read, request-scoped write guard) is sound and was genuinely informed by that prior work, but the provenance as stated was unverifiable against this branch's actual history. Corrected here rather than left standing.

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
9. **AC-9** — Tests: the hook's full state matrix (row exists with mixed true/false values; no row → all four default `true`, no log; read throws/errors → all four default `true`, WITH a logged error — matching AC-4's "log genuine failures" reasoning applied to reads too), rollback/serialization/race-guard behavior, and confirmation (via `git grep`, not just trusting the diff) that no other file still imports the deleted mock exports. **Corrected 2026-08-06 review:** since optimistic-update/rollback/race-guard logic all lives in `useNotificationPreferences` (not the component — a deliberate, better design than splitting it), this behavior is tested exhaustively at the hook layer; the component layer only needs to prove it renders real values and forwards clicks correctly, which it does. AC-6/AC-7 additionally require a real-HTTP-boundary test (MSW, not a mocked service function) per binding rule 2, since a self-constructed mock can't disconfirm the actual request shape. Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions, per the BMAD Pre-Implementation Checklist (this section was missing from Story 2-42 — an oversight this story does not repeat):

1. **Unit of work and range:** one Supabase read (≤1 row, `PRIMARY KEY (user_id)`) on mount, one `PATCH` (1 field per request, never more) per toggle click. No variable-size input exists anywhere in this story — every request touches exactly one user's exactly one row.
2. **Fixed budgets vs. variable input:** N/A with reason — the request body is a fixed 4-optional-boolean shape enforced by the backend's Pydantic schema (`extra='forbid'`); there is no list, no file, no pagination for this frontend to bound.
3. **Scope of every limit:** per-user only — RLS (`auth.uid() = user_id`) on the read, JWT-derived `user_id` on the write. Nothing shared or global is touched.
4. **Unbounded reads/writes:** none. The Supabase read is a single-row `.maybeSingle()` query keyed by primary key; the backend's own write path is already documented as bounded (`test_unbounded_queries.py`-satisfying, per Dev 4's docstring).
5. **Inherited caps re-derived:** none inherited — this is new frontend code calling a freshly-built, already-scale-reviewed backend endpoint (Story 4-23's own 6-layer review covered its scale properties).
6. **Concurrent requests safe?** Backend: read-merge-upsert is last-writer-wins on truly concurrent PATCHes for *different* fields from *different* tabs — an explicitly accepted tradeoff in Dev 4's own docstring ("acceptable for preferences"), not something this story needs to re-solve. Frontend: AC-5's per-field request-generation guard is exactly this question answered for the same-field-rapid-toggle case, which the backend's concurrency story does not cover on its own (two PATCHes for the *same* field from the *same* tab, reordered in flight).

## Tasks / Subtasks

- [x] Task 1 (AC: 2, 9): Build `useNotificationPreferences()` hook — Supabase read of `user_notification_preferences`, defaults-on-no-row, degrade-with-log on error.
  - [x] 1.1 RED: tests for the three read-state cases (row with mixed values / no row → defaults, no log / read error → defaults, WITH log).
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 3, 5, 6, 7): Add `updateNotifications()` to `settings.service.ts` (real `PATCH auth/notifications` call); wire the hook's update function with the per-field request-generation race guard.
  - [x] 2.1 RED: tests that a single-field PATCH fires with no `user_id`, that a stale response can't overwrite a newer one (AC-5), and that the body is never empty.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 1, 4): Rewrite `NotificationsTab.tsx` — 4 toggles (add Session Report), optimistic update + rollback + console.error on failure, using the new hook instead of local `useState`/`useEffect` boilerplate.
  - [x] 3.1 RED: tests that all 4 toggles render with real values, a toggle click calls the real service with the correct single-field payload, and a failure rolls back and logs.
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 8): Delete the in-memory mock plumbing entirely.
  - [x] 4.1 RED: a guard assertion (or manual `git grep`) proving no remaining reference to the deleted exports outside this story's own removed lines.
  - [x] 4.2 GREEN: delete `mocks/api/settings.ts`'s two functions, `mocks/data/users.ts`'s `NotificationSettings` type + `MockUser.notifications` field, `settings.service.ts`'s old mock-delegating methods, and the now-obsolete old test file content.
- [x] Task 5 (AC: 9): Full suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

### Review Findings

4-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter — the latter mandatory per `docs/SCALE-CONTRACT.md`) run 2026-08-06 against `main...sprint3/s3-07-notifications-ui` (commit `d0ecfff`). Raw findings merged/deduped to 18: 0 decision-needed, 9 patch, 7 defer, 2 dismissed as noise (already independently verified true during implementation, the reviewer just couldn't see that blind).

**Patch:**

- [x] [Review][Patch] **Core correctness bug, confirmed independently by 3 of 4 layers**: the success path of `updatePreference` discards the PATCH response entirely and never re-checks the generation guard. Two genuinely successful (not failed) writes to the same field, reordered in flight (backend's own docstring: "last-writer-wins on concurrent PATCHes"), leave the UI showing the *opposite* of what's actually persisted — no error, no warning, both HTTP calls 200. [`apps/web/src/hooks/useNotificationPreferences.ts`]
- [x] [Review][Patch] Cross-user state leak: `requestGenerationRef` is never reset when `userId` changes, so a stale in-flight request from a previous user (logout/login without full reload) can roll back a newly-loaded user's preference. [`apps/web/src/hooks/useNotificationPreferences.ts`]
- [x] [Review][Patch] No cancellation guard in `updatePreference` for a component unmounting mid-request (the mount-time read effect has one via `cancelled`; the write path has no equivalent). [`apps/web/src/hooks/useNotificationPreferences.ts`]
- [x] [Review][Patch] `updatePreference` has no `userId` guard (unlike the read effect), so a call during an invalid/transitional auth state fires a PATCH that can only fail downstream. [`apps/web/src/hooks/useNotificationPreferences.ts`]
- [x] [Review][Patch] `NotificationPreferencesPatch = Partial<NotificationPreferences>` permits the exact empty-object shape AC-7 forbids and the backend 422s on — no type-level guard, only single-call-site discipline. [`apps/web/src/services/settings.service.ts`]
- [x] [Review][Patch] No no-op short-circuit when `updatePreference` is called with the field's current value — fires a redundant network write and generation bump. [`apps/web/src/hooks/useNotificationPreferences.ts`]
- [x] [Review][Patch] Story text claims `useAttentionConsent.ts` (Story 2-42) as this branch's own precedent/reference ("Read `useAttentionConsent.ts` ... before writing anything") — verified false: that file does not exist anywhere in this branch's history (it forked from `main`, which never had it; the file only exists on the unmerged `sprint3-master`/`sprint3/s3-01-*` branches). The design itself is sound, but the stated provenance is inaccurate. [`docs/stories/2-43-notifications-ui.md`]
- [x] [Review][Patch] Binding rule 2 violation: AC-6/AC-7 ("never send `user_id`", "body never empty") are proven only against a self-constructed `vi.fn()` mock of `settingsService.updateNotifications`, with no test hitting the real `api.patch`/HTTP boundary and no `# MOCK-CONTRACT:` marker — and the story's own cited precedent (`ChapterGenerateControl.test.tsx`) actually does the opposite of what this diff does: it deliberately does NOT mock the service, asserting on the real request body via MSW. [`apps/web/src/__tests__/hooks/useNotificationPreferences.test.ts`]
- [x] [Review][Patch] AC-9 literally requires component-level tests of "optimistic-update/rollback/race-guard behavior," but all of that logic was (deliberately, and correctly) moved into the hook — `NotificationsTab.test.tsx` mocks the hook entirely, so no component-level test (or could meaningfully) exercise rollback/race-guard. The Completion Notes' "all ACs satisfied" over-claims against AC-9's literal text; the AC's wording should reflect the actual (better) design rather than a component test being added just to satisfy the letter of it. [`docs/stories/2-43-notifications-ui.md`]

**Defer (deferred, pre-existing or out of scope):**

- [x] [Review][Defer] All PATCH failure types (503 retryable, 500, 401/403 session-expired) are collapsed into identical handling (log + conditional rollback) — no distinction surfaced to the user, no retry-on-503, no re-auth prompt on 401. [`apps/web/src/hooks/useNotificationPreferences.ts`] — deferred, matches how every other non-critical settings toggle in this codebase already behaves; a session-expiry UX improvement is a cross-cutting concern, not specific to notifications.
- [x] [Review][Defer] The hook can't distinguish "auth still resolving" from "genuinely logged out" (`useAuth()`'s own `isLoading` is never checked, only `!userId`), causing a brief flash of default values before the real row loads on a fresh page load. [`apps/web/src/hooks/useNotificationPreferences.ts`] — deferred, **confirmed identical pre-existing pattern in `useAttentionConsent.ts`** (Story 2-42, verified directly against both that hook and `AuthContext.tsx`) — a shared gap across both hooks, not unique to this diff.
- [x] [Review][Defer] Multi-tab divergence: the request-generation race guard is scoped to one hook instance (one tab/mount), not one user/account — two tabs open on the same settings page can each report a successful toggle while persisting two different final values, with no cross-tab reconciliation (no realtime subscription/BroadcastChannel exists anywhere in `apps/web/src`). [`apps/web/src/hooks/useNotificationPreferences.ts`] — deferred; closing this needs a realtime-sync mechanism that doesn't exist anywhere in this codebase yet, out of scope for a single toggle-wiring story.
- [x] [Review][Defer] Unverified assumption that `api.patch` rejects (throws) on a non-2xx response, on which this hook's entire catch/rollback/logging path depends. [`apps/web/src/services/settings.service.ts`] — deferred; shared assumption across every other real service in this codebase (`books.service.ts`, `onboarding.service.ts`, `lib/assessment.ts` all rely on the same axios instance), not new to this diff.
- [x] [Review][Defer] `.maybeSingle<NotificationPreferences>()`'s generic is a compile-time assertion only — a partially-null row or a renamed column would still type-check. [`apps/web/src/hooks/useNotificationPreferences.ts`] — deferred as DEFER-007 in `docs/deferred-work.md`; identical to `useAttentionConsent.ts`'s own unaudited shape on the sibling `sprint3-master` branch — fixing only here would be inconsistent; needs a project-wide premise test once the branches converge.
- [x] [Review][Defer] Brittle DOM-structure-coupled test selectors (`closest('div.flex.items-center.justify-between')`) and log-message string-matching assertions (`stringContaining('failed to read')`). [`apps/web/src/__tests__/hooks/useNotificationPreferences.test.ts`, `apps/web/src/__tests__/components/settings/tabs/NotificationsTab.test.tsx`] — deferred, matches this codebase's own pre-existing, widely-used testing convention (including the very `NotificationsTab.test.tsx` this replaced); not a regression introduced here.

**Dismissed as noise (2):** "unverified default flip for `streak_reminders`" and "direct Supabase read's access control is unverifiable from this diff" — both already independently verified true/correct during implementation (against the real `_NOTIF_DEFAULTS` in `auth/router.py` and the real RLS policy in the migration respectively); the Blind Hunter layer flagged them only because it has no project access to check. Also dismissed: the claim that the race-guard test doesn't reflect real click behavior — verified `NotificationsTab.tsx` re-reads `updatePreference` fresh from the hook on every render (no memoized/stale `onClick`), so the test's sequential `result.current.updatePreference` calls do match how two real rapid clicks would actually resolve in the mounted component.

## Dev Notes

### What NOT to do

- Do NOT write directly to `user_notification_preferences` from the frontend, even though RLS technically permits an own-row `UPDATE`/`INSERT`. The real `PATCH /api/auth/notifications` is the documented, tested, sole writer (Dev 4's own docstring calls this out explicitly) — bypassing it would duplicate the read-merge-upsert logic client-side and lose the backend's validation (extra-field rejection, at-least-one-required) entirely. This is the corrected lesson from Story 2-42's own review: build against the real write endpoint when one exists, don't reach for a client-side Supabase write just because RLS would technically allow it.
- Do NOT invent frontend-only default values for the four toggles. Use the exact same `true` defaults the backend's `_NOTIF_DEFAULTS` and the migration's column `DEFAULT` clauses already declare — a drift here (e.g. defaulting `streak_reminders` to `false` client-side) would show a student a setting that doesn't match what the backend would actually apply on their first real write.
- Do NOT batch multiple toggle changes into a single PATCH call "for efficiency" — each toggle already fires independently today, and AC-3/AC-7 depend on that shape (partial update semantics, body never empty by construction).

### Testing standards

Mock the Supabase client at the module level (`@/lib/supabase/client`'s `createClient()`, not the network level) for the hook's read tests. **Corrected 2026-08-06 review:** the original text here claimed `ChapterGenerateControl.test.tsx` mocks its service function — it does the opposite: no `vi.mock('@/services/books.service')` anywhere, real HTTP through MSW, specifically so the test can disconfirm the real request shape (its own header comment says so explicitly). `settingsService.updateNotifications` IS mocked for the hook's own unit tests (appropriate there — the hook's logic is what's under test, not the network layer), but AC-6/AC-7 (no `user_id`, body never empty) are proven separately with a **real MSW-boundary test** (`settings.service.test.ts`) that never mocks the service, matching what `ChapterGenerateControl.test.tsx` actually does. Per `docs/DEFECT-REGISTER.md` binding rule 2, assert the actual resulting state wherever the assertion allows it.

### References

- [Source: `docs/DEFECT-REGISTER.md` D60 — full history of all four pieces (Dev 3/Dev 1/Dev 4 closed, Dev 2 this story)]
- [Source: `apps/api/app/modules/auth/router.py:66-304` — the real `PATCH /api/auth/notifications` contract, verified directly, not from the cross-team announcement alone]
- [Source: `supabase/migrations/20260806000000_user_notification_preferences.sql` — table schema, column defaults, RLS policies]
- [Source: `apps/web/src/hooks/useAttentionConsent.ts` (Story 2-42, sibling `sprint3-master` branch — NOT present in this branch's own history, see the AC-2 correction above) — the own-row Supabase-read pattern this story's hook design was informed by, though not literally reusable code here]
- [Source: `apps/web/src/services/onboarding.service.ts` — the real-endpoint service-layer convention (`api.VERB<Type>(path, body).then(r => r.data)`) to follow for `settings.service.ts`'s new `updateNotifications`]
- [Source: `apps/web/src/components/settings/tabs/NotificationsTab.tsx` (current) — component being replaced; existing optimistic-update/rollback shape to preserve]
- [Source: `docs/DEFECT-REGISTER.md` D56 — precedent for deleting dead mock plumbing as one deliberate change, not by attrition]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Story created per S3-07 in `docs/dev2-sprint-tracker.md` / D60. Branch `sprint3/s3-07-notifications-ui` off `main` at `1884f2b`. Verified the real `PATCH /api/auth/notifications` contract directly against `apps/api/app/modules/auth/router.py` before writing any AC. | Dev 2 |
| 2026-08-06 | Implemented all 5 tasks, TDD (RED confirmed before each GREEN). All optimistic-update/rollback/race-guard logic ended up living entirely in `useNotificationPreferences` rather than split between hook and component (cleaner than Story 2-42's split, since there's no retry-affordance UI requirement here) — `NotificationsTab.tsx` is a thin renderer. Also fixed a pre-existing bug found while running the full suite: `proxy.test.ts`'s "bookstore" test was missing `email` on its mock user (the same D65 regression already fixed on `sprint3-master`, inherited here since this branch forked from `main` before that fix existed) — same one-line fix applied. Full `apps/web` suite: 67 files / 770 tests passing. `tsc --noEmit` clean. `eslint` clean on every touched file. Status → review. | Dev 2 |
| 2026-08-06 | 4-layer adversarial code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor, and the mandatory Scale & Load Hunter): 18 merged findings, 0 decision-needed, 9 patch, 7 defer, 2 dismissed. Most consequential: 3 of 4 layers independently found that the original per-field request-generation counter only checked staleness on failure, so two genuinely successful writes to the same field, reordered by real server-side commit-order jitter, could leave the UI silently showing the opposite of what actually persisted. Replaced with per-field write serialization (never more than one in-flight request per field). All 9 patches applied, including a compile-time-enforced non-empty patch type, a real MSW-boundary test for AC-6/AC-7, cross-user/unmount/no-op guards, and two story-text corrections. A bug was found and fixed even during the fix itself (see Post-Review Fixes). Full suite: 68 files / 777 tests passing. `tsc --noEmit` clean, `eslint` clean. Status → done. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Read `onboarding.service.ts`, `auth/router.py`, the migration, and the current `NotificationsTab.tsx`/`Toggle.tsx`/mocks fully before writing anything. (The `useAttentionConsent.ts` reference in the original References section turned out not to exist on this branch — corrected during review; the design was informed by that prior work from session context, not literally read from this branch's own files.)
- `settings.service.ts`: kept the file (still the real home for `getProfile`/`getPreferences`/`getPrivacy`, unchanged, out of scope), added `NotificationPreferences`/`NotificationPreferencesPatch`/`NotificationPreferencesRecord` types matching the backend schema field-for-field, and a real `updateNotifications()` using `api.patch`. Removed the old mock-delegating `getNotifications`/`updateNotifications`.
- `useNotificationPreferences.ts`: Supabase read on mount (own-row, `.maybeSingle()`), degrading to `DEFAULT_PREFERENCES` (all `true`, matching the backend's `_NOTIF_DEFAULTS` exactly) on both "no row" and "read error" — the two cases only differ in whether `console.error` fires. `updatePreference` does the optimistic set + real PATCH + rollback-on-failure + logging, all in one place, guarded by a per-field `requestGenerationRef` counter so a stale failure's rollback can never stomp a more recent request's result (AC-5) — proved with a genuine 3-click race test, not a 2-click one, since 2 clicks can coincidentally "pass" by luck of the boolean values involved.
- `NotificationsTab.tsx`: rewritten as a thin renderer driven entirely by the hook — a `TOGGLES` array of `{key, label, description}` maps directly over the backend's 4 real field names, so adding a field in the future is a one-line array entry, not a new JSX block. No local `useState`/`useEffect`/rollback logic left in the component at all.
- Mock removal (AC-8): deleted `NotificationSettings` interface + `MockUser.notifications` field from `mocks/data/users.ts`, and `getNotificationSettings`/`updateNotificationSettings` from `mocks/api/settings.ts`. Verified via `git grep` (not just trusting the diff) that no reference to any of the three remains anywhere in `apps/web/src`.

### Completion Notes

- All 5 tasks complete, all ACs (1-9) satisfied.
- Full `apps/web` suite: 67 files, 770 tests, all passing (13 new: 8 in `useNotificationPreferences.test.ts`, 5 in `NotificationsTab.test.tsx`; the old 5-test `NotificationsTab.test.tsx` was fully replaced, not appended to, since none of its assertions matched the new real contract).
- `tsc --noEmit`: clean. `eslint`: clean on every touched file (one non-issue: an `eslint-disable-next-line react-hooks/set-state-in-effect` comment on the `!userId` branch's `setIsLoading(true)` turned out unnecessary once written — same false-positive-avoidance shape already seen in `useAttentionConsent.ts`; removed rather than left as a silencing no-op).
- Confirmed AC-6 (no `user_id` in the request body) and AC-7 (body never empty) directly in the hook test by inspecting `updateNotificationsMock.mock.calls[0]`'s actual keys, not just that the mock was called (`docs/DEFECT-REGISTER.md` binding rule 2).
- Found and fixed a pre-existing, unrelated bug while verifying the full suite: `proxy.test.ts`'s bookstore-sibling-route test was missing `email` on its mocked user (D65, previously fixed on `sprint3-master` but not on `main` directly — this branch forked from `main` before that fix existed). Same one-line fix applied here; worth applying to `main` directly too in a follow-up since it's unrelated to this story.
- This story is entirely real end-to-end today — no placeholder/mock-backed piece remains for notifications, unlike Story 2-42's consent flow at the time it shipped.

### Post-Review Fixes (2026-08-06)

Applied all 9 patch findings. The most consequential: replaced the original per-field **request-generation counter** design with **per-field write serialization** (a queue of at most one in-flight + one pending write per field). Three of four review layers independently found the same root bug — the generation counter only checked staleness on *failure*, so two genuinely *successful* writes to the same field, reordered by real network jitter (the backend's own PATCH handler is documented last-writer-wins with no version/ETag), could leave the UI showing the opposite of what actually persisted, with zero errors. A client-side counter checked after the fact cannot fix a server-side commit-order race; only never sending two overlapping requests for the same field can. Also added: cross-user reset (a request's own captured `userId` is checked before it's allowed to touch state, not just cleared refs, since an already-in-flight closure survives a user switch), an unmount guard, a `userId` guard on `updatePreference`, a real no-op short-circuit (via a dedicated `lastIntentRef` that updates synchronously, unlike the `preferences` state which lags one render), a compile-time-enforced non-empty patch type (`AtLeastOneKey<T>` via a `singleFieldPatch()` helper, replacing `Partial<T>`), a real MSW-boundary test for AC-6/AC-7 (`settings.service.test.ts`, no mocked service — satisfies binding rule 2), and two story-text corrections (a false in-branch precedent claim, and AC-9's wording to match the actual, better design). Full suite re-run: 68 files / 777 tests passing (4 new in `settings.service.test.ts`; `useNotificationPreferences.test.ts` grew from 8 to 11 tests covering the new serialization/cross-user behavior). Also fixed a bug found during this pass itself: converting the write-drain loop from a `.then()/.catch()` chain to `async`/`await` (to satisfy an ESLint `react-hooks` rule against self-referential callbacks) initially computed the "is this user still current" check as a plain boolean *before* the `await`, silently defeating the whole guard — caught immediately by the cross-user test actually failing, not assumed correct. Fixed by re-reading `userIdRef.current` fresh after the await, not snapshotting it before. `tsc --noEmit` clean, `eslint` clean.

### File List

- `apps/web/src/hooks/useNotificationPreferences.ts` (NEW — per-field write serialization via an async drain loop, not a generation counter or self-recursive callback, after review)
- `apps/web/src/services/settings.service.ts` (MODIFIED — real `updateNotifications`, `AtLeastOneKey` patch type + `singleFieldPatch()` helper, removed `getNotifications`)
- `apps/web/src/components/settings/tabs/NotificationsTab.tsx` (REWRITTEN — 4 real toggles, thin renderer over the new hook)
- `apps/web/src/mocks/api/settings.ts` (MODIFIED — removed `getNotificationSettings`/`updateNotificationSettings`)
- `apps/web/src/mocks/data/users.ts` (MODIFIED — removed `NotificationSettings` type + `MockUser.notifications` field)
- `apps/web/src/__tests__/hooks/useNotificationPreferences.test.ts` (NEW/REWRITTEN post-review — 11 tests, serialization + cross-user)
- `apps/web/src/__tests__/components/settings/tabs/NotificationsTab.test.tsx` (REWRITTEN)
- `apps/web/src/__tests__/services/settings.service.test.ts` (NEW post-review — real MSW-boundary test for AC-6/AC-7)
- `apps/web/src/__tests__/proxy.test.ts` (MODIFIED — unrelated D65 fix, same one-line bug as `sprint3-master`, inherited from `main`)
