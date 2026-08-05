---
baseline_commit: b199537
---

# Story 2.42: Attention Consent Modal Component (S3-01)

Status: review

## Story

As a student about to start my first lesson,
I want a clear explanation of how the tutor's webcam-based attention monitoring works, and a real choice to decline it,
so that I can make an informed DPDP-compliant decision before any camera access is requested, with no penalty either way.

**Source:** `docs/dev2-sprint-tracker.md` §12, S3-01 (Sprint 3, P0 — "must exist before camera access"). Epic: `docs/bmad/epics/epic-2-lesson-player.md` names `AttentionMonitor`'s DPDP gate explicitly (line 55): *"checks `user_consents` for `consent_type='attention_capture'` before initializing — shows consent modal if absent."*

**Dependency note — read before starting:** the real persistence endpoint (`PATCH /api/users/consent`, and the deeper `user_consents` audit-table writer CLAUDE.md §18 actually requires) **does not exist anywhere yet** — not on `main`, not on Dev 3's own unmerged Sprint 3 branch (`origin/master-sprint3-dev3`), which was verified directly: a repo-wide search for `user_consents` on that branch finds only migration references, docs, and test strings, zero write code, and that branch's own `deferred-work.md` states the consent-write path "needs a deliberate decision with Dev 3/Dev 1... not a frontend-only fix," unresolved as of this story's baseline. This is the tracked defect **D29**, owned by Dev 3.

This story builds the modal and its consent-gating logic fully, against the contract the tracker already specifies, the same "build against contract, flip to real later" pattern as Stories 2-40/2-41 (S3-03/S3-04). The `PATCH /api/users/consent` call will 404 in real use until D29 closes — that is expected, out of this story's scope, and must degrade gracefully per AC-7 below, not crash or block the student.

**Also not yet built (separate future stories, do not implement here):** `AttentionMonitor` (S3-02) and the MediaPipe pipeline it would gate. This story's job is the modal and the read/gate logic *around* where that component will eventually mount — there is no camera code to write yet, and none should be added.

## Acceptance Criteria

1. **AC-1** — New `AttentionConsentModal.tsx` (`apps/web/src/components/player/`). Explains, in plain language: the webcam is used only for attention monitoring, only 5 aggregate numbers are ever sent (never raw video), and the student can decline with no consequence. Two actions: **Accept** and **Decline** (or **"Not now"** — copy is this story's call, not a fixed string from the tracker).
2. **AC-2** — On **Accept**: calls `PATCH /api/users/consent` (new `usersService.setAttentionConsent(true)` in a new `apps/web/src/services/users.service.ts`, matching this codebase's service-layer convention — see `books.service.ts`/`assessment.ts` for the real-endpoint pattern to follow). On success, the modal closes and the decision is remembered (AC-5) so it never shows again for this account.
3. **AC-3** — On **Decline**: no API call is made (there is nothing to accept), the modal closes, and the decision is remembered (AC-5) so it never re-prompts. Per the tracker: **declining must not degrade the lesson in any way** — no different messaging, no disabled features, no nagging banner.
4. **AC-4** — **CRITICAL SECURITY CONSTRAINT, verbatim from the tracker:** the actual gate for whether attention monitoring may ever initialize is `users.attention_consent === true`, loaded fresh from Supabase on every check — **never trusted from `localStorage` or any other client-only cache**. This story does not yet have an `AttentionMonitor` to gate (S3-02, not built), but the read path built here (AC-6) must be the thing that future gate reads, and it must query Supabase directly, not a local flag.
5. **AC-5** — **Design decision (documented here since the tracker's own AC — "shown exactly once" — cannot be satisfied by `attention_consent` alone: that boolean cannot distinguish "never asked" from "asked and declined," and there is no backend field for the latter):** a `localStorage` key (e.g. `hie:attention-consent-dismissed:{user_id}`) records that the modal has been shown and answered *at all* (Accept or Decline), purely to avoid re-prompting every lesson. This key is **never** read by the security-relevant initialize-gate (AC-4) — it only controls whether the *modal* renders, not whether monitoring may start. If a user declines, clears their browser storage, and is asked again, the worst case is being asked again, not an unauthorized initialize — the gate itself always re-checks Supabase.
6. **AC-6** — New `useAttentionConsent()` hook (`apps/web/src/hooks/`) exposing `{ consentStatus: 'accepted' | 'declined' | 'unknown', isLoading, showModal, accept, decline }`. Reads current consent by querying the `users` table's `attention_consent` column directly via the Supabase client (`supabase.from('users').select('attention_consent').eq('id', user.id).single()`) — matching the exact pattern `proxy.ts`'s onboarding gate already uses for a own-row, RLS-scoped read (`proxy.ts:40-44`), not a new backend GET endpoint. `showModal` is `true` only when consent is not yet `true` AND the localStorage dismissal key (AC-5) is absent.
7. **AC-7** — Failure handling: if the `PATCH` in AC-2 fails (404 today, since D29 is unresolved; any other error in the future), the error is logged (`console.error` is correct here — this is a genuinely unexpected failure, not a normal user action, per the reasoning already established in `SignInForm.tsx`/`SignUpForm.tsx`) and the modal shows an inline retry option. The student is never blocked from continuing to the lesson either way — a failed Accept must not trap the student behind the modal.
8. **AC-8** — Mounted in `Player.tsx`, self-contained (reads its own state via the new hook, no props), positioned so it doesn't collide with existing overlays (`CheckingInTransition`, `TutorInterventionCard` from Story 2-40, `CESIndicator` from Story 2-41 — none of which are on this story's `main` baseline yet, so mount independently and expect a trivial merge later, same note as those two stories carried).
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

## Dev Notes

### What NOT to do

- Do NOT build any part of `AttentionMonitor` or reference `getUserMedia`/MediaPipe here — that is S3-02, a separate, not-yet-started story. This story ends at "the modal exists and correctly tracks consent," not "the camera turns on."
- Do NOT gate the real initialize-decision on `localStorage` — AC-4 is a hard security constraint from the tracker, verbatim. The dismissal key from AC-5 is a UX convenience for the *modal's visibility*, never a substitute for reading `attention_consent` from Supabase.
- Do NOT build the backend `PATCH /api/users/consent` endpoint or the `user_consents` table writer — that is D29, owned by Dev 3, explicitly out of scope. Build the frontend call against the contract and let it 404 until he ships it.
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

### File List

- `apps/web/src/services/users.service.ts` (NEW)
- `apps/web/src/hooks/useAttentionConsent.ts` (NEW)
- `apps/web/src/components/player/AttentionConsentModal.tsx` (NEW)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — mounts `<AttentionConsentModal />`)
- `apps/web/src/__tests__/hooks/useAttentionConsent.test.ts` (NEW)
- `apps/web/src/__tests__/components/player/AttentionConsentModal.test.tsx` (NEW)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED — new shared `useAttentionConsent` mock + one new mount-presence test)
