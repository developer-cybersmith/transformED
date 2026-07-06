# Story 2-4: Session Report Page v1

Status: ready-for-dev

## Story

As a student who just finished a lesson,
I want to see a summary of how that session went (quiz accuracy, teach-back outcome, focus/engagement, and how long I studied),
so that I get a sense of progress without being shown clinical scores, and can easily jump back into the lesson to study again.

## Context

This is Sprint 2 task **S2-04** from `docs/dev2-sprint-tracker.md` §11. Its original sketch (file path, endpoint) has two corrections established during research for this story — both **already confirmed with the user**, do not re-litigate:

### Correction 1 — route, to avoid colliding with an unrelated, unbuilt "Reports" concept

There are **two different "reports" concepts** already partially scaffolded in this codebase — easy to conflate, and the reason this story exists separately from that other concept:

1. **A pre-existing, unbuilt, cross-session "learning progression" analytics page** — `Sidebar.tsx` and `QuickActions.tsx` both already have nav links/cards labeled "Reports" pointing at a static `/reports` route ("View your learning progression"). Backed by `reportsService.getReports()` / `mocks/api/reports.ts` / `mocks/data/reports.ts`, returning an aggregate shape (streak, per-topic mastery scores, focus quality, a 5-day study-time chart, concept-completion list). **This has zero live callers anywhere and does not correspond to this story.** It is explicitly **out of scope** — do not touch `reportsService`, `mocks/api/reports.ts`, `mocks/data/reports.ts`, or the existing Sidebar/QuickActions `/reports` nav links/copy.
2. **This story** — a single-session report keyed by `session_id`, matching the real, live Dev 3 backend contract (see below).

The original tracker sketch pointed both concepts at the same file (`src/app/reports/page.tsx`), which cannot work for both at once. **Resolved route for this story:** `src/app/reports/[sessionId]/page.tsx` (dynamic segment — matches the real API's `/session/{id}/report` shape directly). The static `/reports` index page remains unbuilt and is someone else's future task.

### Correction 2 — the real backend contract, verified directly against live code

The tracker's own sketch said "Fetches `GET /api/session/{id}/report`. Mock response used until Dev 3 delivers API." **Verified false as of this story**: the endpoint is real, live, and implemented — confirmed by reading `apps/api/app/modules/assessment/router.py:106-132` directly (not just trusting `docs/dev3-assessment-tracker.md`'s self-reported status, and not just trusting `docs/stories/3-19-session-report-api.md`, though that story's account matches the live code exactly). Full contract details below in Dev Notes.

**A real, pre-existing type bug was found and must be fixed as part of this story:** `apps/web/src/types/assessment.ts`'s existing `SessionReport.ces_breakdown` interface uses wrong key names (`quiz_accuracy`, `teachback_score` nested inside `ces_breakdown`) that do not match the real, frozen backend contract's actual keys (`quiz`, `teachback`, `behavioral`, `head_pose`, `blink` — see AC 7 of story 3-19 and `router.py:34-44`). This has had no live caller until now, so the bug was never caught. Must be corrected as part of Task 1 below, or every field read off `ces_breakdown` in this story's UI will silently be `undefined`.

**Known cross-team blocker (does not block this story, only end-to-end manual QA against a real live session):** nothing in `apps/api` currently INSERTs a row into the `sessions` Postgres table that `get_session_report` reads from — confirmed by grepping the entire `apps/api` tree for `.table("sessions").insert` and finding zero results; the tutor/WebSocket module (`apps/api/app/core/websocket.py`) only touches Redis keys (`tutor_state:{session_id}`, etc.), never Postgres. This is the same already-documented gap noted in `docs/app-audit-2026-07-04.md` finding #5 ("quiz/teach-back submissions ... hit the real backend with bogus IDs. Needs real backend session-creation work"). **Build and test this story entirely with mocked `getSessionReport` responses at the unit-test level** (same pattern `QuizOverlay.test.tsx`/`TeachBackModal.test.tsx` already use via `vi.mock('@/lib/assessment', ...)`) — do not attempt to manually QA against a real session, none can exist yet. Do not build a mock-service-layer toggle for this (see Dev Notes — `lib/assessment.ts`'s existing precedent calls the real endpoint directly, no mock flag).

## Acceptance Criteria

1. **Route & entry point:** `src/app/reports/[sessionId]/page.tsx` renders `src/components/reports/SessionReport.tsx`, fetching the report by the `sessionId` route param.
2. **`Player.tsx` wiring:** the lesson-complete (`status === 'ENDED'`) screen (`apps/web/src/components/player/Player.tsx` ~line 90) currently has a literal placeholder string `"Session report available in Sprint 2"` — replace it with a real link/button to `/reports/{sessionId}`, using `sessionId` from `usePlayerStore((s) => s.sessionId)`. Keep the existing "Back to Dashboard" link alongside it.
3. **Data fetching:** add `getSessionReport(sessionId: string): Promise<SessionReport>` to `apps/web/src/lib/assessment.ts`, calling `api.get<SessionReport>(\`/assessment/session/${sessionId}/report\`)` — matching the exact pattern and file already used by `submitQuiz`/`submitTeachBack` in that file (real endpoint, no mock-service-layer toggle).
4. **Type fix (real bug, must fix):** correct `apps/web/src/types/assessment.ts`'s `SessionReport.ces_breakdown` to use the real, frozen backend key names — `{ quiz: number; teachback: number; behavioral: number; head_pose: number; blink: number }` — replacing the current wrong shape (`quiz_accuracy`, nested `teachback_score`, index signature).
5. **Quiz accuracy shown as a real percentage** (this is normal/expected feedback, not a "clinical score"): render `quiz_score` (0–100 or `null`) as e.g. "78% correct". When `null` (zero quiz attempts this session), show "No quiz questions this session" instead of a percentage. **Per-segment breakdown is explicitly out of scope for v1** — the real backend only returns one aggregate `quiz_score` for the whole session, not a per-segment array; do not invent per-segment data that does not exist in the response.
6. **Teach-back shown as a qualitative descriptor, never a raw number** — same hard-constraint family already enforced on `TeachBackModal.tsx` earlier this sprint (CLAUDE.md: no clinical/rubric scores shown to students). Map `teachback_score` (0–100 or `null`) to a short encouraging phrase via a pure function (e.g. `>=80` → "Strong grasp", `>=60` → "Solid understanding", `<60` → "Needs another look", `null` → "No teach-back this session"). Never render the raw number.
7. **CES shown as a descriptive label only, never a raw number** (explicit instruction on this task in `docs/dev2-sprint-tracker.md` §11 S2-04, consistent with the teach-back rule above). Map `ces_score` (0–100 float) via a pure function to a label (e.g. `>=80` "Highly Engaged", `>=60` "Well Focused", `>=40` "Getting There", `<40` "Room to Grow" — exact wording is a product/copy decision, not fixed by this AC, but it MUST be non-numeric). **Do not render a per-component `ces_breakdown` chart in v1** — 3 of its 5 components (`behavioral`, `head_pose`, `blink`) are always `0.0` in Sprint 2 (attention data doesn't exist until Sprint 3's MediaPipe work), so a breakdown visualization would show a confusing, mostly-empty chart. Defer that to the Sprint 3 task that already exists for it (`docs/dev2-sprint-tracker.md` §12, "Session report: attention timeline chart").
8. **Engagement summary:** render `interventions_count` (int) and `duration_minutes` (float) in friendly, non-raw-number-dump phrasing (e.g. "42 minutes studied", "3 focus check-ins" — exact copy is a product decision, just don't dump raw field names/JSON at the student).
9. **Completed timestamp:** if `completed_at` is non-null, show a human-readable date/time (reuse or extend `formatTimeAgo` in `lib/utils.ts` if suitable, or format directly — dealer's choice, just no raw ISO string in the UI).
10. **"Study Again" button:** routes to `/lesson/{lesson_id}` using the `lesson_id` field from the fetched `SessionReport` response itself (already present in the response — no extra prop/plumbing needed).
11. **Loading state:** a skeleton or spinner shown while the fetch is in flight (match the existing `PlayerLoader.tsx` skeleton pattern/visual language where reasonable).
12. **Empty/error state:** if the fetch fails for any reason (404 because the session doesn't exist/isn't owned by the caller, network error, etc.), show a friendly message (not raw error text) plus a link back to `/dashboard`. Do not distinguish 404 from other failures in the UI copy — the backend's own SEC-006 rule (session-ownership 404s look identical to nonexistent-session 404s) means the frontend shouldn't try to be smarter than the API about *why* it failed.
13. **Authorization:** no extra frontend work needed — `lib/api.ts`'s existing request interceptor already attaches the Supabase JWT to every request; the backend enforces per-user ownership (HTTP 404 for another user's session, SEC-006). Just don't bypass the shared `api` client.
14. **Tests:** component tests for `SessionReport.tsx` mocking `getSessionReport` (matching the `vi.mock('@/lib/assessment', ...)` pattern from `QuizOverlay.test.tsx`/`TeachBackModal.test.tsx`) covering: loading state, populated happy path (all fields render, CES/teach-back rendered as labels not numbers — a regression guard equivalent to the one added for `TeachBackModal.test.tsx`'s score-leak fix), `quiz_score`/`teachback_score` both `null` (zero-attempt session), fetch failure → error state, "Study Again" link target. Unit tests for the new CES-label and teachback-label pure functions covering every band boundary.

## Tasks / Subtasks

- [ ] Task 1: Fix the pre-existing type bug (AC: #4)
  - [ ] 1.1 Correct `SessionReport.ces_breakdown` shape in `apps/web/src/types/assessment.ts` to `{ quiz, teachback, behavioral, head_pose, blink }` (all `number`), matching `router.py:34-44` / story 3-19 AC 7 exactly
- [ ] Task 2: Data layer (AC: #3, #4)
  - [ ] 2.1 Add `getSessionReport(sessionId)` to `apps/web/src/lib/assessment.ts`
  - [ ] 2.2 Add `useSessionReport(sessionId)` to `apps/web/src/hooks/useSessionReport.ts`, mirroring `useLesson.ts`'s SWR pattern exactly (see Dev Notes)
  - [ ] 2.3 Write failing test(s) first (RED) if a `lib/assessment.test.ts`/`useLesson.test.ts`-equivalent convention exists, or cover via the component test's mock in Task 4 if not — check for existing test files before creating new ones
- [ ] Task 3: Pure label-mapping functions (AC: #6, #7)
  - [ ] 3.1 Write failing tests for a CES-score → label function and a teachback-score → label function, covering every band boundary and the `null` case (RED)
  - [ ] 3.2 Implement both functions (GREEN) — colocate in `src/components/reports/` or `src/lib/` per whatever convention `formatTimeAgo` already establishes in this codebase
- [ ] Task 4: `SessionReport` component + page (AC: #1, #5, #6, #7, #8, #9, #10, #11, #12, #13)
  - [ ] 4.1 Write failing component tests first (RED) — loading, happy path incl. score-leak regression guard, null-scores case, error state, Study Again link
  - [ ] 4.2 Implement `src/components/reports/SessionReport.tsx` and `src/app/reports/[sessionId]/page.tsx` (GREEN)
- [ ] Task 5: Wire the lesson-complete screen (AC: #2)
  - [ ] 5.1 Update `Player.tsx`'s `ENDED` block: replace the "Session report available in Sprint 2" placeholder with a real link to `/reports/{sessionId}`, sourced from `usePlayerStore((s) => s.sessionId)`
  - [ ] 5.2 Confirm the existing `InteractivePlayer.test.tsx`/`Player`-adjacent tests (if any exist for the ENDED screen) still pass; add one if none currently cover this screen
- [ ] Task 6: Full verification
  - [ ] 6.1 Full `apps/web` test suite green
  - [ ] 6.2 `npx tsc --noEmit` clean
  - [ ] 6.3 `npx eslint .` — zero new errors (main is currently at 0 errors / 37 pre-existing warnings; do not regress that)
  - [ ] 6.4 Update `docs/dev2-sprint-tracker.md` S2-04 entry to DONE with file list and today's date

## Dev Notes

### Real, frozen backend contract (verified directly in live code, not just docs)

`GET /api/assessment/session/{session_id}/report` (full path — `lib/api.ts`'s axios `baseURL` already includes `/api`, so call `api.get('/assessment/session/{id}/report')` exactly like `submitQuiz`/`submitTeachBack` call `/assessment/quiz` / `/assessment/teachback`). Requires auth (`CurrentUser` — handled automatically by `api.ts`'s interceptor). Verified in `apps/api/app/modules/assessment/router.py:34-44` (schema) and `:106-132` (handler):

```python
class SessionReport(BaseModel):
    session_id: str
    user_id: str
    lesson_id: str
    ces_score: float
    ces_breakdown: dict[str, float]   # exactly 5 keys: quiz, teachback, behavioral, head_pose, blink
    interventions_count: int
    quiz_score: float | None
    teachback_score: float | None
    duration_minutes: float
    completed_at: str | None
```

- `quiz_score` / `teachback_score`: 0.0–100.0, or `null` when that session had zero attempts of that type.
- `ces_breakdown["behavioral"|"head_pose"|"blink"]`: always exactly `0.0` in Sprint 2 (Phase 3/Sprint 3 concern — do not build UI implying these are meaningful yet).
- 404 (not 403) for both "session doesn't exist" and "session belongs to another user" (SEC-006, prevents ID-enumeration) — same detail string either way, frontend must not try to distinguish.
- Full detail and the 5-agent adversarial review that hardened this endpoint: `docs/stories/3-19-session-report-api.md`.

### Existing precedent to follow, not reinvent

`apps/web/src/lib/assessment.ts` already has `submitQuiz`/`submitTeachBack` calling the real endpoint directly via the shared `api` client, no mock-service-toggle layer (unlike `lesson.service.ts`/`dashboard.service.ts`, which do use a mock/real toggle — assessment endpoints are the one domain in this codebase that skip that layer). Follow the same direct-call pattern for `getSessionReport` for consistency within this one file/domain. Existing types this task must NOT duplicate: `QuizResult`, `TeachbackResult` already exist in `types/assessment.ts` — do not create parallel/duplicate types.

**Data-fetching pattern — mirror `useLesson.ts` exactly, do not invent a different approach:** `apps/web/src/hooks/useLesson.ts` establishes the fetch-with-SWR convention already used for the player's own data loading (`useSWR` keyed by id, `{ data, isLoading, error }` shape, `revalidateOnFocus: false`). Create `apps/web/src/hooks/useSessionReport.ts` following that identical shape:

```typescript
export function useSessionReport(sessionId: string) {
  const { data, error, isLoading } = useSWR<SessionReport | null>(
    sessionId ? `session-report:${sessionId}` : null,
    async () => (await getSessionReport(sessionId)) ?? null,
  );
  return { report: data ?? null, isLoading, error };
}
```

`SessionReport.tsx` consumes this hook — do not fetch inline with `useEffect`/`useState` when the SWR pattern is already established and tested elsewhere in this exact codebase.

### Files this story touches

- `apps/web/src/types/assessment.ts` (MODIFY — fix `ces_breakdown` shape, real bug)
- `apps/web/src/lib/assessment.ts` (MODIFY — add `getSessionReport`)
- `apps/web/src/hooks/useSessionReport.ts` (NEW — mirrors `useLesson.ts`'s SWR pattern)
- `apps/web/src/components/reports/SessionReport.tsx` (NEW)
- `apps/web/src/app/reports/[sessionId]/page.tsx` (NEW)
- `apps/web/src/components/player/Player.tsx` (MODIFY — ENDED screen link, ~line 90)
- Test files: `apps/web/src/__tests__/components/reports/SessionReport.test.tsx` (NEW), plus wherever the CES/teachback label functions land

### What NOT to do

- Do NOT touch `reportsService`, `mocks/api/reports.ts`, `mocks/data/reports.ts`, or the Sidebar/QuickActions `/reports` nav links — separate, out-of-scope, unbuilt concept.
- Do NOT invent per-segment quiz accuracy data — the real API doesn't return it.
- Do NOT render `ces_score`, `teachback_score`, or a `ces_breakdown` chart as raw numbers anywhere.
- Do NOT build a mock-service-toggle layer for this endpoint — follow `lib/assessment.ts`'s existing real-call-only precedent.
- Do NOT attempt manual end-to-end QA against a real live session — none can exist yet (see Context above); rely on mocked unit/component tests.

### Project Structure Notes

No conflicts with `packages/shared` frozen contracts (`LessonPackage`/`ws.ts`) — this story only touches Dev 2's own `apps/web/src` tree and reads (never writes) `apps/api`.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-04 — Session Report Page v1] (original sketch; route/endpoint corrected above)
- [Source: docs/stories/3-19-session-report-api.md] (real backend contract + its own adversarial review)
- [Source: apps/api/app/modules/assessment/router.py:34-44,106-132] (live verification of the contract)
- [Source: apps/web/src/types/assessment.ts#SessionReport] (existing but incorrect FE type — fix, don't duplicate)
- [Source: apps/web/src/lib/assessment.ts] (existing pattern to extend)
- [Source: apps/web/src/components/player/Player.tsx#L90] (placeholder text to replace)
- [Source: apps/web/src/stores/player.machine.ts#sessionId] (id to thread through)
- [Source: apps/web/src/__tests__/components/player/TeachBackModal.test.tsx] (score-leak regression-guard test pattern to replicate for CES/teachback labels)
- [Source: docs/app-audit-2026-07-04.md#finding-5] (known cross-team session-creation blocker, does not block this story)

## Dev Agent Record

### Agent Model Used

(fill in during dev-story)

### Debug Log References

### Completion Notes List

### File List
