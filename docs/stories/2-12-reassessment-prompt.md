---
baseline_commit: 79b46ce79ef07a6f71737bab2e6e97079b35e9b0
---

# Story 2.12: Re-Assessment Prompt After 10 Sessions (Dev 2 counterpart to Story 3-31)

Status: review

## Story

As a student who has completed 10 (or 20, or 30...) sessions,
I want to be gently reminded that my Learner DNA profile is due for a refresh,
so that I can choose to retake the 20-question diagnostic and get more accurate personalization going forward.

**Source:** Dev 3's **Story 3-31** ("Re-Assessment Prompt After 10 Sessions" — `docs/stories/3-31-reassessment-prompt.md`, merged to `main`) added a `reassessment_due: boolean` field to `GET /api/assessment/user/dna`, set `true` every 10th completed session until the diagnostic is re-submitted. This story is the frontend counterpart — **fully feasible end-to-end, verified directly against the real shipped backend, not assumed**:

- **The frontend type already has this field.** `apps/web/src/types/assessment.ts`'s `LearnerDNA` interface already declares `reassessment_due: boolean` (line 130) — matching the backend's `LearnerDNA` Pydantic model (`router.py:68`, `reassessment_due: bool = False`) field-for-field. No type change needed.
- **`onboardingService.getLearnerDna()` already exists** (`apps/web/src/services/onboarding.service.ts:8-9`) and already calls the real `GET /assessment/user/dna` endpoint. No new service function needed.
- **Resubmission is confirmed to need no special-casing on the frontend.** Read the actual backend submit endpoint (`apps/api/app/modules/assessment/router.py:209-215`, `main`): when `reassessment_due` is set, the backend deletes its own idempotency lock *before* the `SET NX` check, so the exact same `POST /onboarding/submit` call that would otherwise 409 for an already-onboarded user instead succeeds (201) and clears the reassessment flag afterward. The frontend genuinely does not need a different code path for first-time vs. re-assessment submission.

> **⚠️ Post-review correction (2026-07-23):** the "verified directly against the real shipped backend" claim above was checked against `main`, but is **false for `sprint2-master`** — the branch this story's own branch is built off and will actually merge into. Confirmed independently three ways (Edge Case Hunter, Acceptance Auditor, and a direct `git merge-base --is-ancestor` check run by the dev agent): `main` and `sprint2-master` have fully diverged; `git show sprint2-master:apps/api/app/modules/assessment/service.py` still hardcodes `"reassessment_due": False` unconditionally, and `sprint2-master`'s `POST /onboarding/submit` has no reassessment-bypass logic at all. **Practical consequence: on `sprint2-master` today, `reassessment_due` can never actually be `true` — this entire feature (mount-check fix + dashboard banner) is currently inert (unreachable, not broken) until Dev 3's Story 3-31 backend commits (`1f713d3` et al.) are merged into `sprint2-master`.** The frontend code itself is correct against the real, eventual contract and is forward-compatible — no code change was made in response to this finding — but do not expect to see this feature functionally light up in a `sprint2-master` build until that backend sync happens. See the Senior Developer Review section below.

**But there IS a real, blocking gap that must be fixed as part of this story** — found by tracing what actually happens today if a student clicks a hypothetical "Take Assessment" CTA and lands on `/onboarding`:

`apps/web/src/components/onboarding/OnboardingFlow.tsx`'s mount effect (lines 81-107) calls `getLearnerDna()` and, on ANY success response (200), unconditionally does `clearPersistedProgress(); router.push("/dashboard")` — it never inspects `reassessment_due` at all. **An already-onboarded student navigating to `/onboarding` today is bounced straight back to `/dashboard` before ever seeing the question flow, even if `reassessment_due` is `true` and the backend would genuinely accept a resubmission.** Without fixing this, a "Take Assessment" CTA would be completely non-functional — it would link to a page that immediately redirects away. This story must fix that mount-check logic, not just add a banner.

## Acceptance Criteria

1. **AC-1 — `OnboardingFlow.tsx`'s mount check respects `reassessment_due`.** When `getLearnerDna()` succeeds on mount: if `reassessment_due === true`, proceed into the flow (same `"disclaimer"`/`"questions"` phases a first-time user gets — do not invent a different UI path); if `reassessment_due === false` (the current, only behavior today), keep the existing redirect-to-dashboard behavior unchanged.
2. **AC-2 — a dismissible re-assessment prompt on the dashboard.** A new component, mounted on `apps/web/src/app/(dashboard)/dashboard/page.tsx`, does its own client-side `getLearnerDna()` fetch and shows a dismissible banner when `reassessment_due === true`. Not a blocking modal — the student can dismiss and keep using the app.
3. **AC-3 — dismiss state keyed on `session_count`, not a single boolean.** Store the dismissal in `localStorage` keyed on the specific `session_count` value that triggered it (e.g. `dismissed_reassessment_prompt_at_session_10`), so dismissing at session 10 does not suppress the prompt when it fires again at session 20. (Per Dev 3's guide's own explicit pitfall warning — this one detail from the guide is corroborated by the backend's own repeating-every-10-sessions design, so treat it as accurate.)
4. **AC-4 — CTA navigates to `/onboarding`.** Clicking the prompt's CTA (e.g. "Update My Profile") navigates to the existing onboarding form — the same route and component used for first-time onboarding, per AC-1's fix.
5. **AC-5 — no special submission handling needed, confirmed not built.** `OnboardingFlow.tsx`'s existing submit logic (`onboardingService.submitOnboarding`) is used unchanged for a re-assessment resubmission — do not add a parallel "resubmit" code path or a different payload shape. This is confirmed via the real backend code cited above, not assumed.
6. **AC-6 — DNA cache/state naturally refreshes.** After a successful re-assessment resubmission, the student is already routed through the same success flow as first-time onboarding (showing `DNAResultCard`) — no explicit "invalidate cache" step is needed beyond what already happens today, since `OnboardingFlow.tsx` doesn't use a stale-cache-prone data layer (SWR, etc.) for this flow; the dashboard prompt's own next mount will simply re-fetch and see `reassessment_due: false`.
7. **AC-7 — no regression.** All existing `OnboardingFlow.tsx` behavior (first-time disclaimer/questions/result flow, 409-already-submitted handling, persisted-progress resume, 401/422/500 error handling) continues to work exactly as today for a user whose `reassessment_due` is `false`.
8. **AC-8 — tests.** Cover: `OnboardingFlow.tsx` shows the flow (not a redirect) when `reassessment_due: true`; still redirects when `reassessment_due: false` (regression); the new dashboard prompt renders when due and is absent when not due or when the DNA fetch fails/is pending; dismissing the prompt hides it and persists across a remount; the dismissal from session 10 does NOT suppress a later prompt at session 20 (different `session_count`); the CTA navigates to `/onboarding`.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 7): `apps/web/src/components/onboarding/OnboardingFlow.tsx` — update the mount-check `.then()` branch to inspect `reassessment_due` before deciding to redirect vs. proceed into the flow.
  - [x] 1.1 RED: a test with `getLearnerDnaMock.mockResolvedValueOnce({..., reassessment_due: true})` asserting the disclaimer/questions phase renders, NOT a redirect to `/dashboard`.
  - [x] 1.2 RED: a test with `reassessment_due: false` (or omitted, matching today's existing tests) confirming the existing redirect-to-dashboard behavior is unchanged — this should already pass without modification if Task 1.2's implementation is done correctly; treat any break here as a real regression.
  - [x] 1.3 GREEN.
- [x] Task 2 (AC: 2, 4): Create `apps/web/src/components/dashboard/sections/ReassessmentPrompt.tsx` — a client component that calls `onboardingService.getLearnerDna()` on mount, renders a dismissible banner when `reassessment_due === true`, with a CTA button navigating to `/onboarding` (`useRouter().push('/onboarding')`, matching `HeroSection.tsx`'s existing navigation pattern). Renders nothing while loading, on fetch failure, or when not due.
  - [x] 2.1 RED: tests for renders-when-due / absent-when-not-due / absent-on-fetch-failure / CTA-navigates.
  - [x] 2.2 GREEN.
- [x] Task 3 (AC: 3): Dismiss behavior — clicking a dismiss control hides the banner and persists that to `localStorage` keyed on the specific `session_count`; a later mount with a *different* `session_count` (even if still `reassessment_due: true`) shows the prompt again.
  - [x] 3.1 RED: tests for dismiss-hides-and-persists-across-remount, and dismiss-at-session-10-does-not-suppress-session-20.
  - [x] 3.2 GREEN.
- [x] Task 4: Mount `<ReassessmentPrompt />` in `apps/web/src/app/(dashboard)/dashboard/page.tsx` (a Server Component — mounting a `"use client"` component inside it is normal Next.js App Router usage, no other change to this file needed).
- [x] Task 5 (AC: 8): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.
- [x] Task 6: Tracker update — note this in `docs/dev2-sprint-tracker.md`.

### Review Follow-ups (AI)

- [x] [AI-Review][Medium] `ReassessmentPrompt.tsx`'s dismiss-state was keyed only on `session_count`, with no `user_id` — a shared/public-machine multi-account leak (dismissal by one user suppresses the prompt for a different user landing on the same `session_count`). Fixed: dismiss key is now `dismissed_reassessment_prompt_{user_id}_at_session_{session_count}`.
- [x] [AI-Review][Medium] `OnboardingFlow.tsx`'s reassessment-due branch resumed any persisted `sessionStorage` progress with no check that it belonged to *this* reassessment instance — a stale abandoned attempt from an earlier due `session_count` could silently resume against a later, different one. Fixed: `PersistedProgress` now carries `dueSessionCount`; resume is only honored when it matches the current `dna.session_count`. (Also fixed a related bug this surfaced: `loadPersistedProgress()` was reconstructing the returned object field-by-field and silently dropping the new `dueSessionCount` field — added it to the reconstruction.)
- [x] [AI-Review][Low] `ReassessmentPrompt.tsx` returned `null` for the whole component (including `AnimatePresence`) on dismiss, so the intended exit fade never actually played. Fixed: the dismiss/not-due condition is now evaluated as a conditionally-rendered child *inside* an always-mounted `AnimatePresence`, with an `exit` transition, so `AnimatePresence` can properly animate removal.
- [x] [AI-Review][Low] No `aria-live`/`role="status"` on the banner, so screen readers wouldn't announce it appearing asynchronously after the client-side fetch resolves. Fixed: added `role="status" aria-live="polite"`.
- [ ] [AI-Review][Low] Duplicate `GET /assessment/user/dna` calls between `ReassessmentPrompt` and `OnboardingFlow` (no shared cache) — explicitly accepted per AC-6's own reasoning; deferred, not a defect.
- [ ] [AI-Review][High — branch state, not a code defect] `sprint2-master` lacks Story 3-31's backend entirely (see the post-review correction note under Story/Context above) — this frontend story's code is correct and forward-compatible, but the feature is inert until Dev 3's backend commits are synced into `sprint2-master`. No frontend code change applies here; flagged for Dev 2/Dev 1 coordination before this is expected to demo functionally.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/web/src/types/assessment.ts`**: `LearnerDNA` (lines 125-132) already has `reassessment_due: boolean` — confirmed matching the backend's `LearnerDNA(BaseModel)` in `apps/api/app/modules/assessment/router.py:60-68` (`reassessment_due: bool = False`) field-for-field. **No change needed to this file.**
- **`apps/web/src/services/onboarding.service.ts`** (full file, 10 lines): `getLearnerDna: () => api.get<LearnerDNA>('assessment/user/dna').then((r) => r.data)` — already real, already correct. **No change needed to this file.**
- **`apps/web/src/components/onboarding/OnboardingFlow.tsx`**: mount effect at lines 81-107:
  ```tsx
  useEffect(() => {
    let cancelled = false;
    onboardingService.getLearnerDna()
      .then(() => {
        if (!cancelled) {
          clearPersistedProgress();
          router.push("/dashboard");
        }
      })
      .catch((err) => { /* 401 -> /signin; 404 -> disclaimer/questions; other -> fail open into flow */ });
    return () => { cancelled = true; };
  }, []);
  ```
  The `.then()` callback receives nothing today (it's `.then(() => {...})`, discarding the resolved `LearnerDNA` value entirely) — Task 1 needs to actually capture it (`.then((dna) => {...})`) to read `dna.reassessment_due`.
- **`apps/web/src/app/(dashboard)/dashboard/page.tsx`** (full file, 49 lines): a Server Component (`async function DashboardPage`), currently renders `HeroSection`, `ContinueLearningCard`, `QuickActions`, `LearningPulse`, `RecentLessons` — all fed by `dashboardService.getDashboard()` (still mock-backed, `apps/web/src/services/dashboard.service.ts` — irrelevant to this story, the new prompt component does its own independent real fetch, not routed through this mock).
- **`apps/web/src/components/dashboard/sections/HeroSection.tsx`**: reference for this story's new component's conventions — `"use client"`, `useRouter()` for navigation, `Button` from `@/components/ui/button`, `framer-motion` for entrance animation, `rounded-2xl` styling. Match this, don't invent a new visual language.
- **No dashboard-visible DNA UI exists anywhere today.** Confirmed via grep — `getLearnerDna`/`LearnerDNA` are referenced only inside the onboarding flow (as a first-time-vs-returning gate check, and as the 409-fallback display), never as a persistent, standalone "your Learner DNA" surface. This story's `ReassessmentPrompt` is the first thing to put DNA-derived state on the dashboard.

### What the real backend actually does (verified against `main`, not assumed)

```python
# apps/api/app/modules/assessment/router.py — GET /user/dna (line 60-68)
class LearnerDNA(BaseModel):
    user_id: str
    badge_labels: list[str]
    profile_text: str | None
    session_count: int
    reassessment_due: bool = False
    last_updated: str | None

# POST /onboarding/submit (line 209-222) — re-assessment bypass:
if await redis.get(reassessment_key) is not None:
    await redis.delete(onboarding_key)   # clears the idempotency lock
was_set = await redis.set(onboarding_key, "1", nx=True)
if not was_set:
    raise HTTPException(409, "Onboarding diagnostic has already been submitted for this account.")
# ... process_onboarding() runs normally, then the reassessment flag is cleared afterward.
```
This confirms Dev 3's guide's claim ("same frontend form + API call, backend handles idempotency internally") is accurate for the *submission* side. It is a genuinely different situation from the *mount-check* side, which the guide didn't call out at all and which required tracing `OnboardingFlow.tsx`'s actual code to discover.

### What NOT to do

- Do NOT build a separate "resubmit" API call, payload shape, or code path — `submitOnboarding()` is reused exactly as-is; the backend already handles first-time vs. re-assessment transparently.
- Do NOT make the re-assessment prompt a blocking modal — it must be dismissible and non-blocking (per Dev 3's own guide, and matching general UX sense for a non-critical reminder).
- Do NOT store dismissal as a single boolean — it must be keyed on `session_count` (AC-3), or the prompt would wrongly stay suppressed forever after the first dismissal.
- Do NOT touch `apps/web/src/types/assessment.ts` or `apps/web/src/services/onboarding.service.ts` — both are already correct; this story is UI + one real mount-check bug fix.
- Do NOT touch `dashboard.service.ts` or attempt to wire the dashboard's other (still-mock) sections to anything real — out of scope, unrelated.
- Do NOT touch any backend file.

### Project Structure Notes

Touches: `apps/web/src/components/onboarding/OnboardingFlow.tsx` (MODIFY — mount-check fix), `apps/web/src/components/dashboard/sections/ReassessmentPrompt.tsx` (NEW), `apps/web/src/app/(dashboard)/dashboard/page.tsx` (MODIFY — mount the new component), and their test files. No backend touches, no shared-contract changes, no new dependencies.

### Testing standards

Vitest + `@testing-library/react` + `@testing-library/user-event`. For `OnboardingFlow.tsx` changes, match `OnboardingFlow.test.tsx`'s existing `vi.mock('@/services/onboarding.service', ...)` pattern exactly. For the new `ReassessmentPrompt.tsx`, use the same mocking approach for `onboardingService.getLearnerDna`. For `localStorage`-based dismiss-state tests, use the real `window.localStorage` (clear it in `beforeEach`, matching how `sessionStorage` is already handled in `OnboardingFlow.test.tsx`) rather than mocking the Storage API.

### References

- [Source: docs/stories/3-31-reassessment-prompt.md] — the backend story this responds to (merged, `main`)
- [Source: docs/lm-sprint-frontend-integration.html] — Dev 3's frontend integration guide; useful for the general flow/UX suggestions, but its claims should still be spot-checked against real code per this session's established discipline (its submission-transparency claim checked out this time; its mount-check silence was the real gap found independently)
- [Source: apps/api/app/modules/assessment/router.py] — `LearnerDNA` model, `GET /user/dna`, `POST /onboarding/submit`'s reassessment bypass logic, read via `git show main:...`
- [Source: apps/web/src/types/assessment.ts, apps/web/src/services/onboarding.service.ts, apps/web/src/components/onboarding/OnboardingFlow.tsx, apps/web/src/app/(dashboard)/dashboard/page.tsx, apps/web/src/components/dashboard/sections/HeroSection.tsx, apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx] — all read in full this session, current state documented above

## Senior Developer Review (AI)

**Date:** 2026-07-23
**Outcome:** Changes Requested → all actionable findings resolved this session (see Review Follow-ups above)
**Reviewers:** Blind Hunter (diff-only), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec + context docs) — per CLAUDE.md's BMAD Code Review Gate.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | Medium | Blind Hunter | Dismiss key not scoped to `user_id` — shared-browser multi-account leak | Fixed |
| 2 | Medium | Blind Hunter + Edge Case Hunter (corroborated 2/3) | Stale persisted progress could resume across different reassessment instances | Fixed |
| 3 | Low | Blind Hunter | `AnimatePresence` exit animation was a no-op (early `return null` unmounted the whole tree) | Fixed |
| 4 | Low | Edge Case Hunter | No `aria-live`/`role="status"` on the async-appearing banner | Fixed |
| 5 | Low/informational | Edge Case Hunter | Duplicate `getLearnerDna()` calls (dashboard + onboarding), no shared cache | Deferred — explicitly accepted trade-off per AC-6 |
| 6 | **High** | Edge Case Hunter + Acceptance Auditor (corroborated 2/3), independently verified by dev agent via `git merge-base --is-ancestor` | `sprint2-master` (this story's actual merge target) has fully diverged from `main` and lacks Story 3-31's backend entirely — `reassessment_due` can never be `true` on this branch until Dev 3's backend commits sync over. The story's "verified... not assumed" framing was accurate against `main` but overclaimed relative to the branch it targets. | Documented — see the post-review correction note in Story/Context and Review Follow-ups; no frontend code change applies; flagged for cross-team coordination before functional demo |

### Non-issues checked and dismissed

- `types/assessment.ts`/`onboarding.service.ts` contract match — verified true, unchanged as scoped.
- `localStorage` key collision with `sessionStorage`'s `onboarding_progress_v1` — distinct storage areas, no collision.
- `OnboardingFlow.tsx`'s 404/401/500 `.catch()` and `cancelled` guard — untouched by the diff, composes correctly with the new branch.
- All 8 ACs independently re-verified against the diff by the Acceptance Auditor — satisfied (AC-5/AC-6's backend-transparency premise carved out per finding #6 above).

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-23 | Story created — Dev 2 counterpart to Dev 3's Story 3-31. Confirmed end-to-end feasibility by reading the real backend code (type already matches, resubmission needs no special-casing) and found a real blocking gap in `OnboardingFlow.tsx`'s mount check that must be fixed for a "Take Assessment" CTA to work at all. Branch `sprint2/s2-12-reassessment-prompt` off `sprint2-master`. | Dev 2 |
| 2026-07-23 | Implemented all 6 tasks (RED→GREEN throughout). Fixed `OnboardingFlow.tsx`'s mount-check to inspect `reassessment_due`; created `ReassessmentPrompt.tsx` (dismissible dashboard banner, dismissal keyed on `session_count`); mounted it on the dashboard page. Full `apps/web` suite (47 files / 409 tests), `tsc --noEmit`, and `eslint` all clean. Tracker note added. Status → review. | Dev 2 |
| 2026-07-23 | 5-agent code review round (Blind Hunter, Edge Case Hunter, Acceptance Auditor + Story Quality/Process Integrity per gate). Applied 4 patches (user_id-scoped dismiss key, reassessment-instance-scoped progress resume incl. a `loadPersistedProgress()` field-drop bug this surfaced, real `AnimatePresence` exit animation, `aria-live`/`role="status"`). Documented (not code-patched) a High-severity branch-parity finding: `sprint2-master` lacks Story 3-31's backend, so the feature is currently inert on this branch pending a backend sync — corrected the story's Dev Notes accordingly. Full suite now 47 files / 412 tests, all clean (tsc, eslint). | Dev 2 |

## Dev Agent Record

### Implementation Plan

- **Task 1** — `OnboardingFlow.tsx`'s mount-check `.then()` callback changed from `.then(() => {...})` (discarding the resolved value) to `.then((dna) => {...})`. When `dna.reassessment_due` is true, the same branching logic used in the `.catch()` for "not onboarded yet" (persisted-progress resume vs. fresh disclaimer) is reused, instead of the redirect-to-dashboard path.
- **Task 2/3** — `ReassessmentPrompt.tsx` is a new, self-contained client component. It does its own `onboardingService.getLearnerDna()` fetch on mount (independent of the dashboard page's existing `dashboardService.getDashboard()` server-side call). Dismissal is stored in `localStorage` under `dismissed_reassessment_prompt_at_session_{session_count}` — keying on the specific count (not a single boolean) is what makes a session-20 prompt survive a session-10 dismissal, per AC-3.
- **Task 4** — mounted directly in the Server Component `dashboard/page.tsx`; no `"use client"` boundary issues since `ReassessmentPrompt` declares its own directive.
- Confirmed via revert-and-confirm discipline that the dismiss-persistence test (`dismissing hides the prompt and persists across a remount...`) is a genuine RED without the `localStorage` check in `isDismissed()` — temporarily neutered it, saw exactly 1 failure among the 7 new tests, then restored.

### Completion Notes

- All 6 tasks complete, all ACs (1–8) satisfied.
- Post-review: full `apps/web` test suite: 47 files, 412 tests, all passing (no regressions) — up from 409 after the review round added 3 more tests (user_id-scoping regression test, stale-progress-mismatch test, matching-progress-resumes test).
- `tsc --noEmit`: clean. `eslint` on all touched files: clean.
- No backend changes. No changes to `types/assessment.ts` or `onboarding.service.ts` (both were already correct, as scoped).
- See Senior Developer Review section for the 3-agent review round and the High-severity branch-parity finding (documented, not code-patched — `sprint2-master` lacks Story 3-31's backend).

### File List

- `apps/web/src/components/onboarding/OnboardingFlow.tsx` (MODIFIED)
- `apps/web/src/components/dashboard/sections/ReassessmentPrompt.tsx` (NEW)
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` (MODIFIED)
- `apps/web/src/__tests__/components/onboarding/OnboardingFlow.test.tsx` (MODIFIED)
- `apps/web/src/__tests__/components/dashboard/sections/ReassessmentPrompt.test.tsx` (NEW)
- `docs/dev2-sprint-tracker.md` (MODIFIED — tracker note only)
