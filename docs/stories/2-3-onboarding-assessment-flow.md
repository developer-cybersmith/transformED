---
baseline_commit: 686a8d5
---

# Story 2.3: Onboarding Assessment Flow

Status: ready-for-dev

## Story

As a **student**,
I want to complete a 20-question Learner DNA onboarding assessment — with a legal disclaimer shown up front and a results screen at the end — before I can access lessons,
so that TransformED can personalise my learning experience and I understand, before answering anything, that this is not a clinical assessment.

## Acceptance Criteria

1. Legal disclaimer is shown and must be explicitly acknowledged before question 1 renders. Text (or equivalent DPDP-safe wording): *"This is not a clinical assessment. Scores are used only to personalise your learning experience."*
2. All 20 questions render one at a time with an animated transition (framer-motion, already a dependency) — not all-at-once, not a paginated table.
3. A progress indicator shows "Question X of 20" plus the current dimension label ("Cognitive Style" / "Emotional Profile" / "Self-Direction").
4. User can go back to a previous question and change an answer before final submission; "Next"/"Complete Assessment" is disabled until the current question has a selected option.
5. On the last question, submission POSTs all 20 responses in a single batched request to `POST /api/assessment/onboarding/submit` (endpoint and payload shape below — already correct in the existing page, do not change it).
6. A visible loading state is shown while the submit request is in flight (backend call includes an LLM generation step; expect >1s).
7. On success (HTTP 201), the DNA result screen shows `badge_labels` and `profile_text` **verbatim, including the trailing DPDP disclaimer sentence** — never truncate `profile_text`. Raw numeric dimension scores are never fetched, stored, or rendered anywhere in this flow.
8. No IQ, EQ, or SQ terminology anywhere in UI copy (already satisfied by existing question content — do not introduce it while restyling).
9. From the result screen, an explicit user action (button) navigates to `/dashboard` — do not auto-redirect immediately after showing the result, the student must be able to read their profile first.
10. If the POST returns `409 Conflict` (onboarding already submitted for this account — idempotency lock, see Dev Notes), do not show a generic error. Instead fetch `GET /api/assessment/user/dna` and render the same result screen from that response, then continue to allow navigation to `/dashboard`.
11. If the POST returns `422` (validation error) or any other failure, show a recoverable inline error with a way to retry the submission — the 20 answers already collected in local state must not be lost.
12. On mount, before showing question 1, call `GET /api/assessment/user/dna`. If it resolves `200`, the user has already completed onboarding — skip the questionnaire entirely and route to `/dashboard` (do not force them through 20 questions again; a 404 from this endpoint means "not yet onboarded" and is the normal/expected path into the flow, not an error to surface).
13. `middleware.ts` blocks unauthenticated-of-onboarding access: for any request whose pathname starts with `/lesson` or `/upload`, if the user is signed in but has no `learner_dna` row, redirect to `/onboarding`. Do **not** gate `/dashboard`, `/onboarding`, `/library`, or `/settings` on this check (only `/lesson/**` and `/upload/**`, per existing tracker spec — gating more than this breaks dashboard/library access for a user who hasn't onboarded yet).
14. All 6 existing test cases in `src/__tests__/middleware.test.ts` still pass after the change (update the test doubles as needed — see Dev Notes).
15. Component split matches: `app/onboarding/page.tsx` (route, thin) → `OnboardingFlow.tsx` (owns disclaimer-ack / question index / answers / submit / result state) → `QuestionCard.tsx` (renders one question + its 4 options) → `DNAResultCard.tsx` (renders badges + profile text + continue button). No inline monolith.
16. Visual styling matches the current brand system (S1-15/S1-18): `--accent-primary`/`--accent-secondary` CSS vars, `rounded-2xl`, the shared `Button` component (`@/components/ui/button`) for all actions — not the pre-redesign `slate-*`/`primary-600` Tailwind classes currently in the file being replaced.

## Tasks / Subtasks

- [ ] Task 1: Add typed service layer for onboarding (AC: 5, 7, 10, 12)
  - [ ] 1.1 Create `src/services/onboarding.service.ts` exporting `submitOnboarding(responses: OnboardingAnswer[]): Promise<OnboardingResult>` (POST `assessment/onboarding/submit`) and `getLearnerDna(): Promise<LearnerDNA>` (GET `assessment/user/dna`), both using the existing `api` axios instance from `@/lib/api` (baseURL already includes `/api`, JWT already attached by its interceptor — do not add auth headers manually)
  - [ ] 1.2 Add `OnboardingResult` type to `src/types/assessment.ts` (`{ badge_labels: string[]; profile_text: string; session_count: number }`) next to the existing `OnboardingAnswer`/`OnboardingDiagnosticSubmission`/`LearnerDNA` types — do not rename any existing field in that file, it is a frozen contract file
  - [ ] 1.3 Do not throw/unwrap axios errors inside the service — let `OnboardingFlow` inspect `error.response.status` (409 vs 422 vs other) per AC 10/11

- [ ] Task 2: Build `QuestionCard.tsx` (AC: 2, 3, 4, 16)
  - [ ] 2.1 Props: `{ question: Question; selectedIndex: number | undefined; onSelect: (index: number) => void }` — pure/presentational, no fetch logic
  - [ ] 2.2 Reuse the exact 20-question `QUESTIONS` content already in the current `page.tsx` (content is reviewed/approved per `docs/stories/3-4-onboarding-diagnostic-content.md` — do not edit question text, option text, or IDs)
  - [ ] 2.3 Restyle to brand tokens (`rounded-2xl`, `--accent-primary`), animate question transitions with `framer-motion` `AnimatePresence`/`motion.div` (pattern already used in `HeroSection.tsx`)

- [ ] Task 3: Build `DNAResultCard.tsx` (AC: 7, 8, 9)
  - [ ] 3.1 Props: `{ result: OnboardingResult | LearnerDNA; onContinue: () => void }` — render `badge_labels` as pills/badges, `profile_text` as body copy in full (it already contains the DPDP disclaimer sentence server-side — render as-is, do not append another disclaimer)
  - [ ] 3.2 "Continue to Dashboard" button (`@/components/ui/button`, `variant="primary"`) calls `onContinue`

- [ ] Task 4: Build `OnboardingFlow.tsx` — orchestration (AC: 1, 4, 5, 6, 9, 10, 11, 12, 15)
  - [ ] 4.1 State: `phase: 'checking' | 'disclaimer' | 'questions' | 'submitting' | 'result' | 'error'`, `current: number`, `answers: Record<string,{index:number}>`, `result: OnboardingResult | LearnerDNA | null`, `submitError: string | null`
  - [ ] 4.2 On mount: `phase = 'checking'` → call `getLearnerDna()`. `200` → route to `/dashboard` immediately (AC 12). `404` → `phase = 'disclaimer'`. Any other error → treat as `404` (fail open into the flow, do not hard-block the student on a transient network error)
  - [ ] 4.3 Disclaimer screen: DPDP-safe text (AC 1) + single "I Understand, Begin Assessment" button → `phase = 'questions'`. Do not persist disclaimer acknowledgment anywhere (no backend field exists for it — see Dev Notes gap)
  - [ ] 4.4 Question phase: render `QuestionCard` for `QUESTIONS[current]`, Back/Next per existing logic in current `page.tsx` (reuse, do not redesign the state machine — it already works)
  - [ ] 4.5 On last question's submit: `phase = 'submitting'` → `submitOnboarding(...)`. `201` → `result = response, phase = 'result'`. `409` → call `getLearnerDna()` and use that as `result`, `phase = 'result'` (AC 10). `422`/other → `submitError = message, phase = 'error'` with a Retry button that re-attempts submit without losing `answers` (AC 11)
  - [ ] 4.6 Result phase: render `DNAResultCard`, `onContinue` → `router.push('/dashboard')`

- [ ] Task 5: Wire the route (AC: 15, 16)
  - [ ] 5.1 Replace the body of `src/app/onboarding/page.tsx` with `'use client'; export default function OnboardingPage() { return <OnboardingFlow />; }` — delete the inline `QUESTIONS` array, state, and JSX from `page.tsx` once moved into `OnboardingFlow.tsx`/`QuestionCard.tsx`
  - [ ] 5.2 Confirm the route stays at `apps/web/src/app/onboarding/page.tsx` (the `(dashboard)` route group is NOT used here — `/onboarding` is a top-level route, matching `middleware.ts`'s `PUBLIC_PATHS`/protected-route handling and Epic 2's route map)

- [ ] Task 6: Middleware onboarding gate (AC: 13, 14)
  - [ ] 6.1 Extend `updateSession()` in `src/lib/supabase/middleware.ts` to also return the `supabase` client instance it already constructs (add `supabase` to the returned object — purely additive, existing `supabaseResponse`/`user` fields unchanged)
  - [ ] 6.2 In `src/middleware.ts`, after the existing auth check, add: if `user` exists and `pathname` starts with `/lesson` or `/upload`, query `supabase.from('learner_dna').select('user_id').eq('user_id', user.id).maybeSingle()`; if no row, `return NextResponse.redirect(new URL('/onboarding', request.url))`
  - [ ] 6.3 Update `src/__tests__/middleware.test.ts`: extend `updateSessionMock` resolved values to include a `supabase` stub (`{ from: () => ({ select: () => ({ eq: () => ({ maybeSingle: async () => ({ data: ... }) }) }) }) }`) for every existing test case so the 6 current tests keep passing; add new cases for `/lesson/*` and `/upload/*` with no `learner_dna` row (expect redirect to `/onboarding`) and with a row present (expect pass-through)

- [ ] Task 7: Tests (AC: all)
  - [ ] 7.1 `OnboardingFlow` unit/RTL tests: disclaimer must render and block questions until acknowledged; 20-question happy path submits the correct batched payload shape; 409 path renders result from `getLearnerDna()` instead of an error; 422 path shows retry without clearing answers; mount-time 200 from `getLearnerDna()` skips straight to dashboard redirect
  - [ ] 7.2 `QuestionCard` test: renders 4 options, calls `onSelect` with correct index, disabled state before selection
  - [ ] 7.3 `DNAResultCard` test: renders `badge_labels` and full untruncated `profile_text`, never renders any of the 9 raw dimension-score field names
  - [ ] 7.4 Middleware tests per 6.3

## Dev Notes

### The file you are replacing already exists and mostly works — read it first

`apps/web/src/app/onboarding/page.tsx` is NOT a stub. It is a 195-line functioning implementation with all 20 real, DPDP-reviewed questions, working Back/Next/select state, and a submit call that already hits the **correct** endpoint (`assessment/onboarding/submit`) with the **correct** payload shape (`{ responses: [{question_id, dimension, selected_index, selected_text}] }`). Reuse the `QUESTIONS` array and the Back/Next/selection logic verbatim — do not rewrite content that is already reviewed and approved (`docs/stories/3-4-onboarding-diagnostic-content.md`).

What it's missing, precisely: no legal disclaimer step, no display of the response at all (it silently discards the result and calls `router.push('/dashboard')` immediately after any 2xx), no component decomposition, and pre-redesign styling (`bg-slate-50`, `primary-600`, `dark:` classes) that predates the S1-15/S1-18 brand pass. `[Source: apps/web/src/app/onboarding/page.tsx]`

### The real backend contract is more advanced than the OpenAPI export and epic doc suggest — trust the code below, not the docs

Three sources disagree, in order of staleness:
- `_bmad-output/planning-artifacts/epic-3-assessment-dna.md` describes fields `dna_label`/`profile_narrative`/`cognitive_score` and an endpoint `/api/onboarding/dna` — **none of this exists in the real backend.** This is stale early planning language.
- `docs/openapi-assessment.json` says the submit endpoint returns `202 Accepted` with a generic `{[key:string]:string}` body, and its own description reads `"TODO (Sprint 1): Delegate to assessment service."` — **this OpenAPI export is stale**, generated before the endpoint was finished.
- The actual, current, tested implementation in `apps/api/app/modules/assessment/router.py` + `service.py` (verified against 20+ passing tests in `apps/api/tests/test_onboarding_endpoint.py`) is the ground truth:

```
POST /api/assessment/onboarding/submit   (Bearer JWT required)
  Body:   { responses: OnboardingAnswer[20] }   // OnboardingAnswer = {question_id, dimension, selected_index (0-3), selected_text}
  → 201 Created, body: OnboardingResult { badge_labels: string[]; profile_text: string; session_count: number }
    profile_text ALWAYS ends with "— Pursuant to DPDP Act 2023." — render it in full, never truncate/re-wrap it away.
    Contains no raw numeric dimension scores (already enforced server-side).
  → 409 Conflict if this user already submitted (Redis SET NX key `user:{id}:onboarding_done` — idempotency, not a bug)
  → 422 if not exactly 20 responses, or selected_index outside 0-3, or an invalid dimension value

GET /api/assessment/user/dna   (Bearer JWT required)
  → 200, body: LearnerDNA { user_id, badge_labels, profile_text: string|null, session_count, reassessment_due, last_updated }
  → 404 if the user has no learner_dna row yet — i.e. "not onboarded". This is the EXPECTED response for a
    student who hasn't done onboarding yet, not an error condition to alarm on.
```
`[Source: apps/api/app/modules/assessment/router.py#L106-L204, apps/api/app/modules/assessment/schemas.py#L70-L86, apps/api/tests/test_onboarding_endpoint.py]`

The existing `src/types/assessment.ts` frontend types (`OnboardingAnswer`, `OnboardingDiagnosticSubmission`, `LearnerDNA`) already match this real contract — only `OnboardingResult` is missing from that file (Task 1.2). Do not introduce `dna_label`/`profile_narrative` naming anywhere in the frontend; the real field names are `badge_labels`/`profile_text`.

### `lib/api.ts` already does everything you need
`baseURL` is `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000/api`), and its request interceptor already attaches `Authorization: Bearer <token>` from the Supabase session for every call. Call paths **without** a leading `/api` or leading slash (e.g. `api.post('assessment/onboarding/submit', body)`), matching the existing code and every other service in `src/services/`.

### Middleware: this is the second auth-guard change to this file this sprint — be careful
`S1-13` (2026-07-02) found and fixed a real gap where 4 routes were completely unauthenticated. `src/__tests__/middleware.test.ts` is the regression guard for that fix and currently has 3 `it.each` blocks covering 6 protected paths + 3 public paths, using a mocked `updateSession`. Your change in Task 6 adds a *second* dimension (DNA-completion) on top of the existing session check — it must not weaken the existing session-required behavior, and the existing test file's mocked return value shape will need a `supabase` field added or all 6 pre-existing cases will throw when the new gate code tries to call `.from(...)` on `undefined`.

Do not gate `/dashboard`, `/onboarding`, `/library`, or `/settings` — only `/lesson/**` and `/upload/**`, per `docs/dev2-sprint-tracker.md`'s S2-03 spec. Gating `/dashboard` would make it impossible for a freshly-onboarded user to ever land anywhere, and gating `/onboarding` itself creates a redirect loop.

`GET`-ing `learner_dna` directly via the Supabase client (not the FastAPI backend) in middleware is intentional and mirrors the RLS pattern already proven for `attention_events`/`user_consents` — `learner_dna` has a `select own` RLS policy (`user_id = auth.uid()`), so this is a safe, already-authorized read. `[Source: supabase/migrations/20260611000000_initial_schema.sql#L224-L240 (learner_dna table + RLS), apps/web/src/__tests__/middleware.test.ts]`

### Known gap to flag, not silently fix: DPDP consent for `learner_dna` is not being recorded anywhere

`supabase/migrations/20260702000000_dpdp_user_consents.sql` (Story 3-17, done 2026-07-02) created `user_consents` with `consent_type CHECK (... IN ('attention_tracking', 'learner_dna'))` — the schema explicitly anticipates a consent record for onboarding. But nothing in the current codebase — frontend or `process_onboarding()` backend service — ever inserts a `user_consents` row with `consent_type = 'learner_dna'`. This is the same class of gap that CLAUDE.md §18 already flagged and fixed for `attention_tracking`, just not yet fixed for `learner_dna`.

This story does **not** attempt to fix it — doing so from the frontend (a raw client-side Supabase insert into `user_consents` triggered by the disclaimer "I Understand" button) is architecturally plausible (the table's RLS allows `user_id = auth.uid()` inserts) but should be a deliberate decision made with Dev 3/Dev 1, not something bolted on here without a policy_version or backend coordination. Flag this to the team as a fast-follow story; do not silently skip mentioning it in the PR either.

### Design tokens / component reuse (S1-15/S1-18 brand pass)
- Use `Button` from `@/components/ui/button` for every button in this flow — variants `"primary" | "secondary" | "outline" | "ghost"`, do not hand-roll `<button className="...">` like the current file does.
- Colors: `var(--accent-primary)` / `var(--accent-secondary)`, `rounded-2xl` radii, `neutral-*` grays — see `HeroSection.tsx` for the current reference implementation of these tokens applied to a card + CTA layout.
- Animate with `framer-motion` (already a dependency, `^12.40.0`) — `HeroSection.tsx`'s `motion.section`/`motion.div` with `initial`/`animate`/`transition` is the established pattern for entrance animation; use `AnimatePresence` for the question-to-question transition specifically since it needs exit + enter, which `HeroSection.tsx` doesn't demonstrate.

### Testing standards
Vitest + `@testing-library/react` + `@testing-library/user-event`, `jsdom` environment — see `src/__tests__/middleware.test.ts` for the project's mocking style (`vi.hoisted` + `vi.mock` for module-level dependencies). No new test framework or pattern needed.

### Project Structure Notes

- All new files land under `apps/web/src/components/onboarding/` (new directory) and `apps/web/src/services/onboarding.service.ts` (new file) — both already reserved/empty in `docs/dev2-sprint-tracker.md`'s file map, no conflicts.
- `apps/web/src/app/onboarding/page.tsx` already exists at the correct path — this is an UPDATE, not a NEW file. (One historical note found in `docs/stories/3-4-onboarding-diagnostic-content.md`: an earlier `(app)` route group variant of this page existed and was dropped when routes were merged into `(dashboard)` — irrelevant now, the current top-level `app/onboarding/page.tsx` is correct and is what `middleware.ts` and the Epic 2 route map both expect.)
- No changes needed to `packages/shared/` — this story doesn't touch any frozen shared contract.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-03 — Onboarding Assessment Flow] (original AC list, file targets)
- [Source: _bmad-output/planning-artifacts/epic-2-lesson-player.md#Route Map] (`/onboarding` route ownership = Dev 2)
- [Source: _bmad-output/planning-artifacts/epic-3-assessment-dna.md#Learner DNA Onboarding] (superseded field names — see Dev Notes gap above)
- [Source: apps/api/app/modules/assessment/router.py#L106-L204] (live endpoint contract)
- [Source: apps/api/app/modules/assessment/schemas.py#L70-L86] (OnboardingAnswer/OnboardingDiagnosticSubmission/OnboardingResult)
- [Source: apps/api/tests/test_onboarding_endpoint.py] (proves 201/409/422 behavior)
- [Source: apps/web/src/types/assessment.ts] (frozen frontend contract types — matches live backend, not the epic doc)
- [Source: docs/stories/3-4-onboarding-diagnostic-content.md] (question content provenance + approval)
- [Source: docs/stories/3-17-dpdp-user-consents.md] (`user_consents` schema + the `learner_dna` consent-type gap)
- [Source: supabase/migrations/20260611000000_initial_schema.sql#L224-L256] (`learner_dna`, `onboarding_responses` schema)
- [Source: apps/web/src/middleware.ts, apps/web/src/lib/supabase/middleware.ts, apps/web/src/__tests__/middleware.test.ts] (current auth-guard implementation + regression tests)
- [Source: apps/web/src/components/dashboard/sections/HeroSection.tsx, apps/web/src/components/ui/button.tsx] (current brand design system reference implementation)

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
