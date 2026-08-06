---
baseline_commit: b199537
---

# Story 2.42: Attention Consent Modal Component (S3-01)

Status: done

## Story

As a student about to start my first lesson,
I want a clear explanation of how the tutor's webcam-based attention monitoring works, and a real choice to decline it,
so that I can make an informed DPDP-compliant decision before any camera access is requested, with no penalty either way.

**Source:** `docs/dev2-sprint-tracker.md` §12, S3-01 (Sprint 3, P0 — "must exist before camera access"). Epic: `docs/bmad/epics/epic-2-lesson-player.md` names `AttentionMonitor`'s DPDP gate explicitly (line 55): *"checks `user_consents` for `consent_type='attention_capture'` before initializing — shows consent modal if absent."*

**Dependency note — read before starting:** the real persistence endpoint (`PATCH /api/users/consent`, and the deeper `user_consents` audit-table writer CLAUDE.md §18 actually requires) **does not exist anywhere yet** — not on `main`, not on Dev 3's own unmerged Sprint 3 branch (`origin/master-sprint3-dev3`), which was verified directly: a repo-wide search for `user_consents` on that branch finds only migration references, docs, and test strings, zero write code, and that branch's own `deferred-work.md` states the consent-write path "needs a deliberate decision with Dev 3/Dev 1... not a frontend-only fix," unresolved as of this story's baseline. This is the tracked defect **D29**, owned by Dev 3.

This story builds the modal and its consent-gating logic fully, against the contract the tracker already specifies, the same "build against contract, flip to real later" pattern as Stories 2-40/2-41 (S3-03/S3-04). The `PATCH /api/users/consent` call will 404 in real use until D29 closes — that is expected, out of this story's scope, and must degrade gracefully per AC-7 below, not crash or block the student.

> **Correction, 2026-08-06 code review:** the premise above was wrong about one thing — D29 is specifically that `process_onboarding()` never writes to `user_consents`; it does not mean no write path exists at all. Migration `20260702000000_dpdp_user_consents.sql` (applied 2026-07-02, before this story's baseline) already grants an `"insert own"` RLS policy on `user_consents` and a trigger that syncs `users.attention_consent`. Per the resolved review decision, `accept()` was switched to insert directly into `user_consents` via the Supabase client — the `PATCH /api/users/consent` contract described above was dropped entirely rather than shipped-and-404ing. See Review Findings below.

**Also not yet built (separate future stories, do not implement here):** `AttentionMonitor` (S3-02) and the MediaPipe pipeline it would gate. This story's job is the modal and the read/gate logic *around* where that component will eventually mount — there is no camera code to write yet, and none should be added.

## Acceptance Criteria

1. **AC-1** — New `AttentionConsentModal.tsx` (`apps/web/src/components/player/`). Explains, in plain language: the webcam is used only for attention monitoring, only 5 aggregate numbers are ever sent (never raw video), and the student can decline with no consequence. Two actions: **Accept** and **Decline** (or **"Not now"** — copy is this story's call, not a fixed string from the tracker).
2. **AC-2** — ~~On **Accept**: calls `PATCH /api/users/consent` (new `usersService.setAttentionConsent(true)`...)`~~ **Superseded 2026-08-06 review:** on Accept, inserts directly into `public.user_consents` (`consent_type='attention_tracking'`) via the Supabase client — RLS already permits the own-row write and a DB trigger syncs `users.attention_consent`, so no backend endpoint is needed; `users.service.ts` was removed. On success, the modal closes and the decision is remembered (AC-5) so it never shows again for this account.
3. **AC-3** — On **Decline**: no API call is made (there is nothing to accept), the modal closes, and the decision is remembered (AC-5) so it never re-prompts. Per the tracker: **declining must not degrade the lesson in any way** — no different messaging, no disabled features, no nagging banner.
4. **AC-4** — **CRITICAL SECURITY CONSTRAINT, verbatim from the tracker:** the actual gate for whether attention monitoring may ever initialize is `users.attention_consent === true`, loaded fresh from Supabase on every check — **never trusted from `localStorage` or any other client-only cache**. This story does not yet have an `AttentionMonitor` to gate (S3-02, not built), but the read path built here (AC-6) must be the thing that future gate reads, and it must query Supabase directly, not a local flag.
5. **AC-5** — **Design decision (documented here since the tracker's own AC — "shown exactly once" — cannot be satisfied by `attention_consent` alone: that boolean cannot distinguish "never asked" from "asked and declined," and there is no backend field for the latter):** a `localStorage` key (e.g. `hie:attention-consent-dismissed:{user_id}`) records that the modal has been shown and answered *at all* (Accept or Decline), purely to avoid re-prompting every lesson. This key is **never** read by the security-relevant initialize-gate (AC-4) — it only controls whether the *modal* renders, not whether monitoring may start. If a user declines, clears their browser storage, and is asked again, the worst case is being asked again, not an unauthorized initialize — the gate itself always re-checks Supabase.
6. **AC-6** — New `useAttentionConsent()` hook (`apps/web/src/hooks/`) exposing `{ consentStatus: 'accepted' | 'declined' | 'unknown', isLoading, showModal, accept, decline }`. Reads current consent by querying the `users` table's `attention_consent` column directly via the Supabase client (`supabase.from('users').select('attention_consent').eq('id', user.id).maybeSingle()` — `.maybeSingle()`, not `.single()`, so a missing row degrades to "not yet consented" per AC-9 rather than throwing) — matching the exact pattern `proxy.ts`'s onboarding gate already uses for a own-row, RLS-scoped read (`proxy.ts:40-44`), not a new backend GET endpoint. `showModal` is `true` only when consent is not yet `true` AND the localStorage dismissal key (AC-5) is absent.
7. **AC-7** — Failure handling: if the `user_consents` insert in AC-2 fails (RLS denial, network error, etc.), the error is logged (`console.error` — this is a genuinely unexpected failure, not a normal user action, per the reasoning already established in `SignInForm.tsx`/`SignUpForm.tsx`) and the modal shows an inline retry option. The student is never blocked from continuing to the lesson either way — a failed Accept must not trap the student behind the modal.
8. **AC-8** — Mounted in `Player.tsx`, self-contained (reads its own state via the new hook, no props), positioned so it doesn't collide with existing overlays (`CheckingInTransition`, `TutorInterventionCard` from Story 2-40, `CESIndicator` from Story 2-41 — none of which are on this story's `main` baseline yet, so mount independently and expect a trivial merge later, same note as those two stories carried). **Correction, 2026-08-06 review:** `QuizOverlay`/`TeachBackModal` (unrelated, pre-existing Sprint 2 components) *are* already on `main` and this modal could collide with them — `Player.tsx` now suppresses its render while `status === 'QUIZ' || status === 'TEACH_BACK'`, matching the existing `audioError` exclusion pattern.
9. **AC-9** — Tests: the hook's full state matrix (Supabase returns `true` → `showModal: false`; returns `false`/`null` with no dismissal key → `showModal: true`; returns `false`/`null` WITH a dismissal key present → `showModal: false`; Supabase read failure → degrades to not showing the modal rather than crashing, since a transient read failure must not force-block camera-permission prompting), the modal's Accept/Decline paths (calls the PATCH, sets the dismissal key, closes), the AC-7 failure path (PATCH rejects → inline retry shown, student can dismiss and continue anyway), and confirmation that no camera/`getUserMedia`/MediaPipe API is called anywhere in this story's code (there is nothing to gate yet, but a regression that jumps ahead and wires a camera call here would violate AC-4's "must exist before camera access" ordering). Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean.

## Tasks / Subtasks

- [x] Task 1 (AC: 6): Build `useAttentionConsent()` — Supabase read of `users.attention_consent`, localStorage dismissal check, derived `showModal`.
  - [x] 1.1 RED: tests for the four state-matrix cases in AC-9 (true / false-no-dismissal / false-with-dismissal / read-failure).
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 2, 3, 5): Add `usersService.setAttentionConsent()` to a new `users.service.ts`; wire the hook's `accept()`/`decline()` to call it (accept only) and set the dismissal key (both).
  - [x] 2.1 RED: tests that `accept()` calls the PATCH and sets the dismissal key on success; `decline()` sets the dismissal key with no API call.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 1, 4): Build `AttentionConsentModal.tsx` — explanatory copy, Accept/Decline actions, renders only when the hook's `showModal` is true.
  - [x] 3.1 RED: tests that it renders nothing when `showModal` is false, renders the explanation + both actions when true, and that no camera/MediaPipe API is referenced anywhere in the component or its test.
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 7): Failure handling — PATCH rejection shows inline retry, never traps the student.
  - [x] 4.1 RED: test that a rejected `accept()` call surfaces a retry affordance and that a "continue anyway" path still closes the modal.
  - [x] 4.2 GREEN: implement.
- [x] Task 5 (AC: 8): Mount `<AttentionConsentModal />` in `Player.tsx`.
  - [x] 5.1 RED: `Player.test.tsx` assertion that the component is present in the tree and reflects the hook's state.
  - [x] 5.2 GREEN: implement.
- [x] Task 6 (AC: 9): Full suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

### Review Findings

3-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run 2026-08-06 against `main...sprint3/s3-01-attention-consent-modal` (commit `f7c5e41`). 24 raw findings, merged/deduped to 17: 3 decision-needed, 10 patch, 3 defer, 1 dismissed as noise (an unverified-`api.patch`-throws-on-error assumption already established and shared by every other `*.service.ts` in the codebase). All 3 decision-needed items resolved same day (2 → patch, 1 → accepted-as-is) — final counts: 12 patch, 3 defer.

**Decision-needed — resolved 2026-08-06:**

- [x] [Review][Decision → Patch] Story built `accept()` against a nonexistent `PATCH users/consent` endpoint when a direct Supabase write path already exists and works today — Migration `20260702000000_dpdp_user_consents.sql` (applied 2026-07-02, well before this story's baseline) already created `public.user_consents` with an `"insert own"` RLS policy (`user_id = auth.uid()`) and a trigger that syncs `users.attention_consent = true` on insert of a `consent_type='attention_tracking'` row — the exact own-row Supabase-write pattern this story already uses for reads (`proxy.ts`). Register entry D29 (`docs/DEFECT-REGISTER.md:139`) is specifically that `process_onboarding()` never writes to this table for the onboarding flow — it does not say a frontend-direct insert is blocked. **Decision:** switch `accept()` to insert directly into `user_consents` (`consent_type='attention_tracking'`), bypassing the dead PATCH contract entirely. Moved to Patch below.
- [x] [Review][Decision → Accepted-as-is] Decline leaves zero server-side/audit trace, and the schema has no slot for one (`user_consents.consent_type CHECK IN ('attention_tracking', 'learner_dna')` has no refusal value). **Decision:** accept as-is for now, matching this story's existing Dev Notes decision not to invent a "declined" value client-side. Revisit if compliance raises it — no code change.
- [x] [Review][Decision → Patch] `AttentionConsentModal` can render on top of and block input to `QuizOverlay`/`TeachBackModal` — both already exist on `main` at `z-20`; this modal renders unconditionally at `z-30` with an opaque backdrop and no `pointer-events-none`, with zero awareness of `Player`'s `status`. AC-8 assumed these overlays weren't on baseline yet — that assumption was wrong; they're already on `main`, and the real risk is the async consent read resolving after the player has already advanced past `TEACHING` (verified: `Player.tsx:284` already excludes `audioError`'s overlay from `QUIZ`/`TEACH_BACK`/`ENDED` for the identical reason). **Decision:** apply the same status-exclusion pattern as `audioError` (line 284) — suppress the modal's render while `status === 'QUIZ' || status === 'TEACH_BACK'`. Moved to Patch below.

**Patch:**

- [x] [Review][Patch] Accept/Decline race: a Decline click mid-in-flight-Accept can be silently overwritten when the Accept promise later resolves [`apps/web/src/hooks/useAttentionConsent.ts`, `apps/web/src/components/player/AttentionConsentModal.tsx`]
- [x] [Review][Patch] AC-7's required `console.error` logging is missing from both the modal's accept-failure catch and the hook's own read-failure branches, making genuine failures (including RLS/multi-row errors) unobservable in production [`apps/web/src/hooks/useAttentionConsent.ts`, `apps/web/src/components/player/AttentionConsentModal.tsx`]
- [x] [Review][Patch] Hook doesn't reset state when `user` transitions to `null` (logout mid-lesson), and `accept()` has no `!user` guard unlike `markDismissed()` — stale modal state can persist and fire an API call post-logout [`apps/web/src/hooks/useAttentionConsent.ts`]
- [x] [Review][Patch] A genuine "no row" result (`data: null, error: null`) is conflated with a hard read failure — both currently suppress the modal, but per AC-6 a null/not-yet-true consent value should still show it; only real errors should suppress [`apps/web/src/hooks/useAttentionConsent.ts`]
- [x] [Review][Patch] AC-9's camera/MediaPipe guard test only inspects rendered `document.body.innerHTML`, not the actual source of the hook/service where a regression is more likely to land, despite its own docstring claiming to be "a static, structural guard" [`apps/web/src/__tests__/components/player/AttentionConsentModal.test.tsx`]
- [x] [Review][Patch] Two tests assert only that a mock was called, with no observable-outcome assertion and no `# MOCK-CONTRACT:` marker, violating DEFECT-REGISTER binding rule 2 [`apps/web/src/__tests__/components/player/AttentionConsentModal.test.tsx`, `apps/web/src/__tests__/hooks/useAttentionConsent.test.ts`]
- [x] [Review][Patch] Disclosure-copy tests use loose regexes (`/never/i`, `/webcam/i`) that would pass even if the specific required DPDP claims (5 aggregate numbers, video never leaves the browser) weren't actually present in the copy [`apps/web/src/__tests__/components/player/AttentionConsentModal.test.tsx`]
- [x] [Review][Patch] `isLoading` never resolves to `false` for a signed-out/pre-auth consumer (initialized `true`, effect returns early on `!user` with no corresponding `setIsLoading(false)`) [`apps/web/src/hooks/useAttentionConsent.ts`]
- [x] [Review][Patch] Story's AC-6 text quotes `.single()` verbatim; the shipped code (correctly) uses `.maybeSingle()`, matching `proxy.ts`'s own precedent — update the story text so it doesn't contradict the implementation and its own cited reference [`docs/stories/2-42-attention-consent-modal.md`]
- [x] [Review][Patch] The Supabase read effect is keyed on `[user]` (object identity), but `AuthContext.tsx`'s `onAuthStateChange` handler calls `setUser({...})` with a brand-new object literal on every `TOKEN_REFRESHED` event even when the underlying user hasn't changed — this re-fires the effect (re-querying Supabase, re-flashing `isLoading: true`) on every token refresh, not just on real sign-in/sign-out. Verified directly against `AuthContext.tsx:120-134`, not assumed [`apps/web/src/hooks/useAttentionConsent.ts`]
- [x] [Review][Patch] (resolved decision) Switch `accept()` to insert directly into `public.user_consents` (`consent_type='attention_tracking'`, `policy_version`, `consented_at`) via the Supabase client instead of calling the nonexistent `PATCH users/consent`, matching `proxy.ts`'s own-row write pattern. Update `users.service.ts`/tests accordingly — the PATCH-based `usersService.setAttentionConsent` contract is no longer used by this flow [`apps/web/src/hooks/useAttentionConsent.ts`, `apps/web/src/services/users.service.ts`]
- [x] [Review][Patch] (resolved decision) Suppress `AttentionConsentModal`'s render while `status === 'QUIZ' || status === 'TEACH_BACK'`, matching the existing `audioError` exclusion pattern at `Player.tsx:284` [`apps/web/src/components/player/Player.tsx`, `apps/web/src/components/player/AttentionConsentModal.tsx`]

**Defer (deferred, pre-existing):**

- [x] [Review][Defer] Exported `consentStatus`/dismissal key are easy for a future dev to mistake for the real security gate, and the hook only re-reads Supabase on mount/user-change, not "every check" as AC-4's wording implies [`apps/web/src/hooks/useAttentionConsent.ts`] — deferred, applies to code (`AttentionMonitor`, S3-02) that doesn't exist yet; flag in that story's Dev Notes instead.
- [x] [Review][Defer] Hook's Supabase mocks are hand-shaped to match the implementation exactly, so no test can disconfirm a wrong assumption about the real `.maybeSingle()` response shape [`apps/web/src/__tests__/hooks/useAttentionConsent.test.ts`] — deferred, identical un-premise-tested pattern already shared by `proxy.ts`'s own tests; fixing only here would be inconsistent, needs a project-wide register entry.
- [x] [Review][Defer] No ARIA modal semantics (`role="dialog"`, `aria-modal`, focus trap, Escape handling) on a legally-relevant consent dialog [`apps/web/src/components/player/AttentionConsentModal.tsx`] — deferred, appears to be a shared gap across other modals in this codebase (e.g. `TeachBackModal`), not unique to this diff; candidate for its own register entry covering all modals.

## Dev Notes

### What NOT to do

- Do NOT build any part of `AttentionMonitor` or reference `getUserMedia`/MediaPipe here — that is S3-02, a separate, not-yet-started story. This story ends at "the modal exists and correctly tracks consent," not "the camera turns on."
- Do NOT gate the real initialize-decision on `localStorage` — AC-4 is a hard security constraint from the tracker, verbatim. The dismissal key from AC-5 is a UX convenience for the *modal's visibility*, never a substitute for reading `attention_consent` from Supabase.
- ~~Do NOT build the backend `PATCH /api/users/consent` endpoint or the `user_consents` table writer — that is D29, owned by Dev 3, explicitly out of scope.~~ **Superseded 2026-08-06 review:** this rule assumed no write path existed; `user_consents` already has an own-row RLS insert policy applied since 2026-07-02, so the frontend inserting directly into it (still not the `process_onboarding()` writer D29 actually tracks) is in scope and is what shipped.
- Do NOT invent a "declined" value for `attention_consent` in Supabase — the column is a plain boolean (`true`/`false`/`null`), and writing anything on decline would be inventing backend behavior that isn't Dev 2's call to make. Decline only sets the local dismissal key (AC-5).

### Testing standards

Mock the Supabase client the same way `useLessonSocket.test.ts`/other hook tests in this codebase already do (see `apps/web/src/lib/supabase/client.ts`'s `createClient()` — mock at the module level, not the network level). Mock `usersService.setAttentionConsent` at the service boundary for the modal's own tests, matching how `ChapterGenerateControl.test.tsx` mocks `booksService.generateLesson`. Per `docs/DEFECT-REGISTER.md` binding rule 2, assert the actual resulting state (dismissal key present in storage, hook's `showModal` value) — not merely that a mock function was called.

### References

- [Source: docs/dev2-sprint-tracker.md §12, S3-01 — full spec, the exact PATCH contract, and the CRITICAL SECURITY CONSTRAINT wording quoted verbatim in AC-4]
- [Source: docs/bmad/epics/epic-2-lesson-player.md:55 — `AttentionMonitor`'s DPDP gate description, the origin of "shows consent modal if absent"]
- [Source: docs/DEFECT-REGISTER.md D29 — the backend gap this story deliberately builds against without waiting for]
- [Source: apps/web/src/proxy.ts:38-51 — the exact own-row Supabase-read pattern this story's hook reuses for reading `attention_consent`]
- [Source: apps/web/src/contexts/AuthContext.tsx — confirms `user` from `useAuth()` does NOT carry `attention_consent` (it's derived from `auth.users`/session metadata only); the hook must fetch `public.users` separately]
- [Source: apps/web/src/components/settings/tabs/PrivacyTab.tsx:64-68 — an existing, explicit code comment already distinguishes its local-only "Camera-Based Focus Detection" toggle from this story's real DPDP consent flow; do not conflate the two or treat that toggle as satisfying this story]
- [Source: apps/web/src/components/player/CheckingInTransition.tsx — closest existing precedent for a self-contained, store/hook-driven overlay component mounted directly in `Player.tsx`]
- [Source: apps/web/src/services/books.service.ts — the real-endpoint service-layer pattern (typed request/response, error-message mapping) to follow for the new `users.service.ts`]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-05 | Story created per S3-01 in `docs/dev2-sprint-tracker.md`. Branch `sprint3/s3-01-attention-consent-modal` off `main`. Verified D29 (the blocking dependency) is unresolved on both `main` and Dev 3's own unmerged Sprint 3 branch before starting — see Dependency note above. | Dev 2 |
| 2026-08-05 | Implemented all 6 tasks, TDD (RED confirmed before each GREEN). Full `apps/web` suite: 68 files / 768 tests passing. `tsc --noEmit` clean. `eslint` clean on every touched file (one real fix: `react-hooks/set-state-in-effect` on the deliberate synchronous `setIsLoading(true)`, resolved with the same disable-and-justify pattern `useLessonSocket.ts` already uses). Status → review. | Dev 2 |
| 2026-08-06 | 3-agent adversarial code review: 24 raw findings → 17 (3 decision-needed, 10 patch, 3 defer, 1 dismissed). All 3 decision-needed items resolved with the user (direct `user_consents` insert instead of the dead PATCH endpoint; decline's audit gap accepted as-is; QUIZ/TEACH_BACK overlay collision fixed via status-exclusion). All 12 resulting patches applied. Full `apps/web` suite: 68 files / 774 tests passing. `tsc --noEmit` clean, `eslint` clean. Status stays `review` pending human review/merge. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Read `proxy.ts`, `AuthContext.tsx`, `books.service.ts`, `CheckingInTransition.tsx`, and `PrivacyTab.tsx` fully before writing anything, per the story's own Dev Notes and References.
- `users.service.ts`: new file, one method (`setAttentionConsent`), matching `books.service.ts`'s real-endpoint pattern. Documented inline that the endpoint doesn't exist yet (D29) so a future reader doesn't mistake a 404 for a client bug.
- `useAttentionConsent.ts`: reads `users.attention_consent` via the exact same `.from().select().eq().maybeSingle()` shape `proxy.ts` already uses for `learner_dna`, not a new backend GET. Refactored the initial `.then().catch().finally()` chain to `async`/`await` inside the effect after `tsc` correctly rejected `.catch()` on Supabase's `PromiseLike`-typed builder — cleaner either way. `showModal` is a pure derivation (`!isLoading && !readFailed && consentStatus === 'unknown' && !dismissed`), never a separately-tracked piece of state, so it can't drift out of sync with its inputs.
- `AttentionConsentModal.tsx`: self-contained, reads only from the hook. Failure path (AC-7) reuses `decline()` for "continue without this" — same terminal outcome (dismissed, no consent), different framing text, avoiding a second code path for what is functionally the same action.
- `Player.tsx`: mounted next to `CheckingInTransition`, no props, no other changes. `Player.test.tsx` needed a new shared mock for `useAttentionConsent` (safe default `showModal: false` in the file's existing `beforeEach`) so none of the 34 pre-existing tests — written before this story existed — accidentally render the modal.

### Completion Notes

- All 6 tasks complete, all ACs (1-9) satisfied.
- Full `apps/web` suite: 68 files, 768 tests, all passing (23 new: 8 in `useAttentionConsent.test.ts`, 7 in `AttentionConsentModal.test.tsx`, 1 in `Player.test.tsx`, plus the shared mock/beforeEach changes in `Player.test.tsx` that make the other 34 tests in that file safe against the new mount).
- `tsc --noEmit`: clean. `eslint`: clean on every touched file.
- Confirmed no camera/`getUserMedia`/MediaPipe API is referenced anywhere in this story's code or tests (AC-9's ordering guard) — grepped the diff directly, not just trusted the test.
- This story is entirely usable for real testing today except the one call that will 404: `usersService.setAttentionConsent`. Everything else — the explanation copy, the decline path, the once-only dismissal tracking, the failure/retry UI — works against real Supabase reads right now.

### Post-Review Fixes (2026-08-06)

Applied all 12 patch findings from the code review (3 resolved decision-needed items included): `accept()` now inserts directly into `user_consents` instead of calling the dead PATCH endpoint (`users.service.ts` deleted, nothing else referenced it); `Player.tsx` suppresses the modal during `QUIZ`/`TEACH_BACK`; `console.error` added to both the hook's read/write failure paths and the modal's catch; a decline mid-in-flight-accept is no longer overwritten (request-id guard); the read effect is keyed on `user?.id` instead of the `user` object (was re-firing on every token refresh); a "no row" Supabase result is no longer conflated with a hard read failure; `isLoading` now resolves for a signed-out consumer; the AC-9 camera/MediaPipe guard is now a source-level scan, not a DOM-only check; two mock-only test assertions gained outcome checks; disclosure-copy test assertions tightened to the actual required claims. Full suite re-run green after all fixes (see Change Log). 3 items deferred (DEFER-003 through DEFER-005 in `docs/deferred-work.md`); decline's audit gap accepted as-is per user decision.

### File List

- `apps/web/src/hooks/useAttentionConsent.ts` (MODIFIED — direct `user_consents` insert, request-id race guard, `userId`-keyed effect, no-row vs error distinction, `console.error` on failures)
- `apps/web/src/components/player/AttentionConsentModal.tsx` (MODIFIED — `console.error` on accept failure, updated doc comment)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — mounts `<AttentionConsentModal />`, suppressed during `QUIZ`/`TEACH_BACK`)
- `apps/web/src/services/users.service.ts` (DELETED — superseded by the direct Supabase write; nothing else referenced it)
- `apps/web/src/__tests__/hooks/useAttentionConsent.test.ts` (MODIFIED — rewritten for the direct-insert flow, race guard, token-refresh stability, no-row case, console.error assertions)
- `apps/web/src/__tests__/components/player/AttentionConsentModal.test.tsx` (MODIFIED — source-level AC-9 guard, tightened disclosure-copy assertions, outcome-based retry assertion, console.error assertion)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED — new shared `useAttentionConsent` mock + mount-presence test + 2 new QUIZ/TEACH_BACK suppression tests)
