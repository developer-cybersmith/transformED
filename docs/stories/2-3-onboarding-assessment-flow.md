---
baseline_commit: 686a8d5
---

# Story 2.3: Onboarding Assessment Flow

Status: done

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

- [x] Task 1: Add typed service layer for onboarding (AC: 5, 7, 10, 12)
  - [x] 1.1 Create `src/services/onboarding.service.ts` exporting `submitOnboarding(responses: OnboardingAnswer[]): Promise<OnboardingResult>` (POST `assessment/onboarding/submit`) and `getLearnerDna(): Promise<LearnerDNA>` (GET `assessment/user/dna`), both using the existing `api` axios instance from `@/lib/api` (baseURL already includes `/api`, JWT already attached by its interceptor — do not add auth headers manually)
  - [x] 1.2 Add `OnboardingResult` type to `src/types/assessment.ts` (`{ badge_labels: string[]; profile_text: string; session_count: number }`) next to the existing `OnboardingAnswer`/`OnboardingDiagnosticSubmission`/`LearnerDNA` types — do not rename any existing field in that file, it is a frozen contract file
  - [x] 1.3 Do not throw/unwrap axios errors inside the service — let `OnboardingFlow` inspect `error.response.status` (409 vs 422 vs other) per AC 10/11

- [x] Task 2: Build `QuestionCard.tsx` (AC: 2, 3, 4, 16)
  - [x] 2.1 Props: `{ question: Question; selectedIndex: number | undefined; onSelect: (index: number) => void }` — pure/presentational, no fetch logic
  - [x] 2.2 Reuse the exact 20-question `QUESTIONS` content already in the current `page.tsx` (content is reviewed/approved per `docs/stories/3-4-onboarding-diagnostic-content.md` — do not edit question text, option text, or IDs)
  - [x] 2.3 Restyle to brand tokens (`rounded-2xl`, `--accent-primary`), animate question transitions with `framer-motion` `AnimatePresence`/`motion.div` (pattern already used in `HeroSection.tsx`)

- [x] Task 3: Build `DNAResultCard.tsx` (AC: 7, 8, 9)
  - [x] 3.1 Props: `{ result: OnboardingResult | LearnerDNA; onContinue: () => void }` — render `badge_labels` as pills/badges, `profile_text` as body copy in full (it already contains the DPDP disclaimer sentence server-side — render as-is, do not append another disclaimer)
  - [x] 3.2 "Continue to Dashboard" button (`@/components/ui/button`, `variant="primary"`) calls `onContinue`

- [x] Task 4: Build `OnboardingFlow.tsx` — orchestration (AC: 1, 4, 5, 6, 9, 10, 11, 12, 15)
  - [x] 4.1 State: `phase: 'checking' | 'disclaimer' | 'questions' | 'submitting' | 'result' | 'error'`, `current: number`, `answers: Record<string,{index:number}>`, `result: OnboardingResult | LearnerDNA | null`, `submitError: string | null`
  - [x] 4.2 On mount: `phase = 'checking'` → call `getLearnerDna()`. `200` → route to `/dashboard` immediately (AC 12). `404` → `phase = 'disclaimer'`. Any other error → treat as `404` (fail open into the flow, do not hard-block the student on a transient network error)
  - [x] 4.3 Disclaimer screen: DPDP-safe text (AC 1) + single "I Understand, Begin Assessment" button → `phase = 'questions'`. Do not persist disclaimer acknowledgment anywhere (no backend field exists for it — see Dev Notes gap)
  - [x] 4.4 Question phase: render `QuestionCard` for `QUESTIONS[current]`, Back/Next per existing logic in current `page.tsx` (reuse, do not redesign the state machine — it already works)
  - [x] 4.5 On last question's submit: `phase = 'submitting'` → `submitOnboarding(...)`. `201` → `result = response, phase = 'result'`. `409` → call `getLearnerDna()` and use that as `result`, `phase = 'result'` (AC 10). `422`/other → `submitError = message, phase = 'error'` with a Retry button that re-attempts submit without losing `answers` (AC 11)
  - [x] 4.6 Result phase: render `DNAResultCard`, `onContinue` → `router.push('/dashboard')`

- [x] Task 5: Wire the route (AC: 15, 16)
  - [x] 5.1 Replace the body of `src/app/onboarding/page.tsx` with `'use client'; export default function OnboardingPage() { return <OnboardingFlow />; }` — delete the inline `QUESTIONS` array, state, and JSX from `page.tsx` once moved into `OnboardingFlow.tsx`/`QuestionCard.tsx`
  - [x] 5.2 Confirm the route stays at `apps/web/src/app/onboarding/page.tsx` (the `(dashboard)` route group is NOT used here — `/onboarding` is a top-level route, matching `middleware.ts`'s `PUBLIC_PATHS`/protected-route handling and Epic 2's route map)

- [x] Task 6: Middleware onboarding gate (AC: 13, 14)
  - [x] 6.1 Extend `updateSession()` in `src/lib/supabase/middleware.ts` to also return the `supabase` client instance it already constructs (add `supabase` to the returned object — purely additive, existing `supabaseResponse`/`user` fields unchanged)
  - [x] 6.2 In `src/middleware.ts`, after the existing auth check, add: if `user` exists and `pathname` starts with `/lesson` or `/upload`, query `supabase.from('learner_dna').select('user_id').eq('user_id', user.id).maybeSingle()`; if no row, `return NextResponse.redirect(new URL('/onboarding', request.url))`
  - [x] 6.3 Update `src/__tests__/middleware.test.ts`: extend `updateSessionMock` resolved values to include a `supabase` stub (`{ from: () => ({ select: () => ({ eq: () => ({ maybeSingle: async () => ({ data: ... }) }) }) }) }`) for every existing test case so the 6 current tests keep passing; add new cases for `/lesson/*` and `/upload/*` with no `learner_dna` row (expect redirect to `/onboarding`) and with a row present (expect pass-through)

- [x] Task 7: Tests (AC: all)
  - [x] 7.1 `OnboardingFlow` unit/RTL tests: disclaimer must render and block questions until acknowledged; 20-question happy path submits the correct batched payload shape; 409 path renders result from `getLearnerDna()` instead of an error; 422 path shows retry without clearing answers; mount-time 200 from `getLearnerDna()` skips straight to dashboard redirect
  - [x] 7.2 `QuestionCard` test: renders 4 options, calls `onSelect` with correct index, disabled state before selection
  - [x] 7.3 `DNAResultCard` test: renders `badge_labels` and full untruncated `profile_text`, never renders any of the 9 raw dimension-score field names
  - [x] 7.4 Middleware tests per 6.3

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

### Review Findings

**Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor), 2026-07-04.**

- [x] [Review][Patch] (resolved from Decision) AC16: `QuestionCard`'s 4 option buttons must be refactored to use the shared `Button` component (`className` overrides for `justify-start`/`h-auto`/text-left — Button forwards `className` last through `cn`/`twMerge`, so overrides win) instead of hand-rolled `<button>` elements.
- [x] [Review][Patch] (resolved from Decision) Persist `answers`/`current` question index to `sessionStorage` so a refresh or tab close during the 20-question flow doesn't lose progress.
- [x] [Review][Defer] `phase: "checking"` mount-time `getLearnerDna()` call has no timeout [apps/web/src/components/onboarding/OnboardingFlow.tsx] — deferred: root cause is project-wide (`lib/api.ts`'s shared axios instance has no default `timeout` configured at all, affecting every service); fixing it properly is out of this story's file list.
- [x] [Review][Patch] Middleware silently swallows `learner_dna` Supabase query errors/exceptions (no `error` check, no try/catch) — a transient DB failure gets treated as "not onboarded" and wrongly redirects an already-onboarded user, and an unhandled rejection would crash middleware for all `/lesson`/`/upload` traffic. Inconsistent with this same story's own fail-open policy for `OnboardingFlow`'s mount check. [apps/web/src/middleware.ts]
- [x] [Review][Patch] `ONBOARDING_GATED_PREFIXES` uses naive `pathname.startsWith(prefix)` with no path-segment boundary — would incorrectly sweep in a future sibling route like `/lessons` or `/lesson-plans`. No such route exists today (verified), but the guard is missing. [apps/web/src/middleware.ts]
- [x] [Review][Patch] Error-phase "Retry" button has no `disabled`/`isLoading` guard, unlike the primary "Complete Assessment" button — minor double-submit race risk on rapid double-click. [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Patch] If the 409-recovery `getLearnerDna()` call itself fails, the user lands on a generic error whose only action is "Retry" — which will 409-loop forever since the record already exists server-side. No escape hatch. [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Patch] `DNAResultCard` trusts `badge_labels`/`profile_text` shape from the API with no runtime guard (`.length`/`.map()` on a value whose safety is TS-only). Add a defensive default. [apps/web/src/components/onboarding/DNAResultCard.tsx]
- [x] [Review][Patch] `getStatus`/`getErrorDetail` use ad-hoc duck-typing (`"response" in err`) instead of `axios.isAxiosError` — any unrelated object with a `response` property would be misread as an HTTP error. [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Patch] No 401 handling anywhere in the flow — an expired/invalid session at mount or at final submit is treated as "not onboarded" (mount) or a generic unrecoverable failure (submit) instead of redirecting to `/signin`. [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Patch] Progress bar shows 0% on question 1 and never reaches 100% — off-by-one in `Math.round((current / TOTAL) * 100)` (bug carried over from the deleted legacy file, now re-authored in this diff). [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Patch] `QuestionCard` uses independent `aria-pressed` buttons instead of `role="radiogroup"`/`role="radio"` semantics for a mutually-exclusive single-choice question. [apps/web/src/components/onboarding/QuestionCard.tsx]
- [x] [Review][Patch] Fragile test selector `screen.getAllByText(q.options[0])[0]` in the OnboardingFlow happy-path test helper — silently picks the first match instead of failing loud on an unexpected duplicate. Switch to plain `getByText`. [apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx]
- [x] [Review][Patch] Mount `useEffect`'s `react-hooks/exhaustive-deps` suppression has no comment justifying the assumption that `useRouter()` is referentially stable. [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Patch] AC16: the "Back" button in `OnboardingFlow` is a hand-rolled `<button>`, not the shared `Button` component (every other action in the flow correctly uses it). [apps/web/src/components/onboarding/OnboardingFlow.tsx]
- [x] [Review][Defer] DPDP `user_consents` gap for `consent_type='learner_dna'` [supabase/migrations/20260702000000_dpdp_user_consents.sql] — deferred, already flagged as an intentional cross-team decision in this story's own Dev Notes/Completion Notes (parallel to the fixed `attention_tracking` gap); needs Dev 3/Dev 1 coordination, not a frontend-only fix.
- [x] [Review][Defer] No runtime API-response schema validation or error boundary anywhere in the route tree [apps/web/src/components/onboarding/DNAResultCard.tsx] — deferred, pre-existing project-wide practice gap (no error boundary exists anywhere else in the app either), broader than this story's file list.
- [x] [Review][Defer] Middleware does a live, uncached Supabase round-trip on every `/lesson/**`/`/upload/**` request [apps/web/src/middleware.ts] — deferred, acceptable for Sprint 2 MVP scope; a real fix needs either a client-writable cookie (security regression on a security-relevant gate) or a backend JWT-claim change (out of scope for this frontend story).

**Dismissed (3):** `/dashboard`/`/library`/`/settings` left ungated (this is exactly AC13 as written, not a defect) · `session_count`/`reassessment_due` fields unused in the UI (not required by any AC) · `answers` state typed `Record<string, number>` instead of the spec's `Record<string,{index:number}>` (auditor-confirmed behaviorally equivalent, no AC impact).

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

None — no blocking failures. One test-authoring correction: initial `QuestionCard`/`DNAResultCard` tests used `@testing-library/jest-dom` matchers (`toBeInTheDocument`, `toHaveAttribute`), which aren't registered in `vitest.config.ts` (`setupFiles: []`) and aren't used anywhere else in this codebase's tests. Rewrote to plain DOM assertions (`.not.toBeNull()`, `.getAttribute(...)`) to match the existing convention (see `JargonHover.test.tsx`) instead of adding a new global test setup not requested by the story.

### Completion Notes List

- All 7 tasks implemented and verified with tests; 22 new tests added across service/types/components/middleware, all passing, zero regressions (157/157 total suite passing).
- `apps/web/src/app/onboarding/page.tsx` was a working 195-line monolith, not a stub (flagged in the story's Dev Notes) — reused its `QUESTIONS` content verbatim (moved to `components/onboarding/questions.ts`) and its Back/Next state-machine logic, rather than rewriting reviewed/approved content.
- Backend contract confirmed against live `apps/api` code + passing tests, not the stale `docs/openapi-assessment.json`/epic-3 doc: submit is synchronous 201 with `{badge_labels, profile_text, session_count}`, not async 202. `OnboardingResult` added to `types/assessment.ts` accordingly.
- Middleware gate implemented as a direct Supabase `learner_dna` RLS read (not a FastAPI call) inside `middleware.ts`, extending `updateSession()`'s return shape additively. All 6 pre-existing `middleware.test.ts` cases still pass with the extended mock shape; added 8 new cases for the onboarding gate (gated paths with/without a `learner_dna` row, and confirming dashboard/onboarding/library/settings are never gated).
- 409 (already-submitted) and 422 (validation) submit paths both handled per AC 10/11: 409 transparently fetches and shows the existing DNA via `GET /api/assessment/user/dna`; 422/other shows a Retry that resubmits without losing collected answers.
- Did **not** attempt to fix the DPDP `user_consents` gap for `consent_type='learner_dna'` (flagged in the story's Dev Notes as a real, pre-existing compliance gap parallel to the already-fixed `attention_tracking` one) — that needs a deliberate cross-team decision with Dev 3/Dev 1, not a frontend-only fix bolted onto this story. Raising it as a fast-follow.
- `npx tsc --noEmit` clean. `npx eslint` on all touched files: 0 errors, 1 pre-existing warning in `lib/supabase/middleware.ts` (unused `options` var in a cookie handler I did not touch, outside this story's scope).
- **Post-review update (2026-07-04):** 5-agent adversarial review found 14 real, fixable issues and 3 items needing a product/scope decision from the user. All 14 patches applied (see Change Log for the list); the 3 decisions resolved to: force `QuestionCard`'s option buttons into the shared `Button` component (patched), add `sessionStorage` persistence for in-flight answers (patched), and defer a project-wide axios-timeout fix (logged to `deferred-work.md`). Final suite: 170/170 passing.

### File List

**New:**
- `apps/web/src/services/onboarding.service.ts`
- `apps/web/src/components/onboarding/questions.ts`
- `apps/web/src/components/onboarding/QuestionCard.tsx`
- `apps/web/src/components/onboarding/DNAResultCard.tsx`
- `apps/web/src/components/onboarding/OnboardingFlow.tsx`
- `apps/web/src/__tests__/services/onboarding.service.test.ts`
- `apps/web/src/__tests__/components/onboarding/QuestionCard.test.tsx`
- `apps/web/src/__tests__/components/onboarding/DNAResultCard.test.tsx`
- `apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx`

**Modified:**
- `apps/web/src/types/assessment.ts` (added `OnboardingResult`)
- `apps/web/src/__tests__/types/assessment.test.ts` (added `OnboardingResult` shape test)
- `apps/web/src/services/index.ts` (export `onboarding.service`)
- `apps/web/src/app/onboarding/page.tsx` (replaced monolith with thin `OnboardingFlow` wrapper)
- `apps/web/src/lib/supabase/middleware.ts` (`updateSession` now also returns `supabase`)
- `apps/web/src/middleware.ts` (added onboarding-completion gate for `/lesson/**`, `/upload/**`)
- `apps/web/src/__tests__/middleware.test.ts` (updated mock shape + 8 new gate test cases)

### Change Log

- 2026-07-03: All 7 tasks completed. 22 new tests, 157/157 suite passing, tsc clean, lint clean (1 pre-existing unrelated warning).
- 2026-07-04: 5-agent adversarial code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run against the uncommitted diff. 3 decision-needed items resolved with the user (2 → patch, 1 → defer), 14 patches applied, 3 items deferred to `deferred-work.md`, 3 dismissed as spec-compliant/non-issues. Key fixes: middleware now fails open (not closed) on Supabase errors and uses an exact path-segment gate check instead of a naive `startsWith`; added 401 handling (redirect to `/signin`) at both mount and submit; added a terminal "Continue to Dashboard" escape hatch for the 409-then-DNA-fetch-also-fails case instead of an infinite Retry loop; switched to `axios.isAxiosError` instead of duck-typing; fixed the progress-bar off-by-one; `QuestionCard` now uses `role="radiogroup"`/`role="radio"` and the shared `Button` component for all 4 options; `OnboardingFlow`'s Back button now uses the shared `Button` too; added `sessionStorage` persistence for in-progress answers so a refresh no longer loses them. 13 new tests added for the fixes (170/170 suite passing), tsc clean, lint clean (same 1 pre-existing unrelated warning). Status → `done`.
