---
baseline_commit: fe7851cb11e00f5fe0aff7f96e40bb55510f8e51
---

# Story 2.53: Razorpay Checkout — Frontend (S4-02)

Status: ready-for-dev

## Story

As a student who has generated a lesson,
I want to pay for it via Razorpay's hosted checkout overlay and be taken to the lesson once payment is confirmed,
so that I can unlock and start the lesson without leaving the page or handling any card data myself.

**Source:** `docs/dev2-sprint-tracker.md`'s S4-02, reprioritized after S4-12 (Email Notifications) per the user's 2026-08-25 instruction. The tracker's original S4-02 write-up describes a **Stripe-shaped flow** (`create-checkout-session`, `/payment/success?session_id=`, `/payment/cancel`) that is now stale — Stripe was replaced by Razorpay (ADR-002, 2026-08-24) and the real backend (Story 4-1, branch `razorpay-backend-endpoints-dev3`, reviewed 6-layer, not yet merged into `main`/`sprint4-master`) implements a different, inline-modal flow with no redirect pages at all. This story implements the real flow, grounded directly by reading that branch's code, not by trusting the cross-team integration message alone.

## Current State, Confirmed By Reading Every File This Story Touches

**Frontend — greenfield.** No match anywhere in `apps/web` for `razorpay`, `RazorpayCheckoutButton`, `lesson_access`, or `payments/create-order` (case-insensitive repo search). `docs/dev2-sprint-tracker.md`'s S4-02 section is the only existing reference, and it's stale (Stripe-shaped).

**Backend — real, reviewed, not yet merged.** Read directly from `origin/razorpay-backend-endpoints-dev3` (`apps/api/app/modules/payments/router.py`, `schemas.py`, `service.py`):
- `POST /api/payments/create-order` — requires `ApprovedUser` (same beta-gate dependency as `/lessons` and `/assessment/*`, confirmed by reading `router.py` directly, not assumed). Body: `{lesson_id: string, amount_paise?: number}` — `amount_paise` is accepted but **silently ignored server-side** (price-bypass fix, S4-1 patch 1); the server always uses `lessons.price_paise` from the DB. Response: `{order_id: string, key_id: string, price_paise: number}`. Returns 404 if `lesson_id` doesn't exist.
- `POST /api/payments/webhook` — unauthenticated, HMAC-verified, fulfills `lesson_access` on `payment.captured`. Not called from the frontend at all — it's Razorpay-to-backend, server-to-server.
- **`GET /api/payments/access` does NOT exist on this branch.** Confirmed by reading the full `router.py` — only `create-order` and `webhook` are registered. This matches the cross-team integration message's own caveat ("pending team sign-off"), independently verified here rather than taken on faith.
- **No server-side minimum-price guard exists yet.** `service.py`'s `create_order` passes `lessons.price_paise` straight to `RazorpayProvider.create_order` with no zero/minimum check. Since all lessons currently have `price_paise = 0` in the DB (per the team's own pricing question), a real `create_order` call against today's data **will fail** — Razorpay rejects sub-100-paise (sub-₹1) orders. This is a backend/pricing blocker this story cannot fix, but the frontend must surface that failure clearly (a real 400/500 from `create_order`, not a silent hang) rather than assume it always succeeds.

**Existing conventions to reuse, not reinvent:**
- `apps/web/src/services/*.service.ts` — thin wrapper functions over `@/lib/api`'s shared axios instance (see `onboarding.service.ts`). A new `payment.service.ts` follows this exact shape, re-exported from `services/index.ts`.
- `apps/web/src/lib/api.ts`'s `api` axios instance already attaches the Supabase JWT via a request interceptor — no separate auth wiring needed for `create-order`.
- `apps/web/src/lib/lessonStatusPoll.ts` (S2-27/S3-11) — the established pattern for "poll a status endpoint with a fixed interval and an explicit ceiling, not silent-forever polling." `nextPollInterval()`'s shape (interval while a ref-tracked elapsed time is under a ceiling, `0` to stop) is reused for the payment-access poll, at Razorpay's own timescale (2s interval, per the cross-team message) rather than the lesson-generation timescale (8s/20min).
- `apps/web/src/components/<domain>/...` layout convention (e.g. `components/player/`, `components/settings/tabs/`) — this story's component lives at `components/payment/RazorpayCheckoutButton.tsx`, matching the tracker's original (still-correct) file path.
- Test convention: `apps/web/src/__tests__/<mirrored-path>/<Name>.test.ts(x)`, using MSW/vi mocks consistent with `__tests__/services/onboarding.service.test.ts` and `__tests__/components/player/*.test.tsx`.

## Acceptance Criteria

1. **AC-1 (order creation)** — Clicking the checkout button calls `POST /api/payments/create-order` with `{lesson_id}` via the shared `api` client (real JWT auth, no `amount_paise` sent from the client — the server ignores it anyway, and sending it would misleadingly imply the frontend controls price). On success, receives `{order_id, key_id, price_paise}`. On failure (404 lesson not found, 400/500 from a price/Razorpay error), surfaces a visible error state — never a silent no-op.
2. **AC-2 (Razorpay script + modal)** — `checkout.js` (`https://checkout.razorpay.com/v1/checkout.js`) is loaded on demand (not in the root `<head>` for every page — only pages that render the checkout button pay this cost), exactly once even if the button is clicked multiple times or mounted more than once. `new Razorpay({key: key_id, order_id, amount: price_paise, currency: "INR", handler: onSuccess}).open()` opens Razorpay's own hosted overlay — no custom card form, matching the "card/UPI data never touches our frontend" constraint carried over from the Stripe-era spec.
3. **AC-3 (post-payment confirmation poll)** — On `handler(response)` firing (`{razorpay_payment_id, razorpay_order_id, razorpay_signature}`), the button shows a "confirming payment" state and polls `GET /api/payments/access?lesson_id=` every 2s until `{has_access: true}`, then redirects to the lesson player (`/lesson/{lesson_id}`). The poll has an explicit ceiling (Scale & Load Q2) — this is NOT the lesson-generation timescale, so a much shorter ceiling applies (see Scale & Load below); past the ceiling, show an explicit "still confirming, this is taking longer than expected" state, never silent infinite polling and never a false "it worked."
4. **AC-4 (mocked access check, explicitly flagged, not silently faked)** — `GET /api/payments/access` does not exist on the backend yet (confirmed above, independently of the cross-team message). Per that message's own guidance, this story builds against a **clearly labeled mock** (`checkAccess` in `payment.service.ts` resolves `{has_access: true}` unconditionally, on the very first call — there is no simulated delay or "not yet" tick built into the mock itself; the poll loop's "not yet" branch is only exercised by tests that explicitly override the mock) so the UI flow (button → modal → poll → redirect) is fully buildable and testable now. This is registered as **D136** (`docs/DEFECT-REGISTER.md`, binding rule 5 — a documented limitation must carry a register ID, not just a code comment) with an explicit swap-out task once the real endpoint lands. The mock must be isolated behind the same `payment.service.ts` function signature the real call will use, so swapping it is a one-function change, not a component rewrite.
5. **AC-5 (no dead Stripe-era routes)** — Per the cross-team message, do NOT build `/payment/success`, `/payment/cancel`, or a `create-checkout-session` call — those are Stripe-shaped and have no backend counterpart on the real branch. The lesson player redirect (AC-3) is the only "success" surface; a failed/abandoned Razorpay modal (closed without paying) simply returns the button to its pre-click state, no dedicated cancel page.
6. **AC-6 (tests)** — Component tests for: successful create-order → modal open (mocking the `Razorpay` global), create-order failure (404 and 500) surfacing a visible error, the access-poll reaching `has_access: true` and redirecting, and the poll ceiling being hit (surfaced, not silent). Service tests for `payment.service.ts`'s `createOrder`/`checkAccess` request shapes. A guard test confirming the client never sends `amount_paise` (AC-1's price-integrity note) and never references any of the AC-5 dead routes.

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** one checkout attempt, per (user, lesson) pair. A student may retry after a failed/abandoned payment — the component must support being clicked again after any terminal state (error, poll-ceiling-hit), not just the happy path once.
2. **Fixed budgets vs. variable input:** the access-poll ceiling is the only new fixed budget this story introduces. Set to **60 seconds** (30 attempts at the 2s interval from the cross-team spec) — Razorpay's own webhook delivery is typically sub-second to a few seconds; 60s is generous headroom for webhook queueing/retry delay without leaving a student staring at a spinner indefinitely. Past the ceiling: explicit "taking longer than expected" state (never silent), matching `lessonStatusPoll.ts`'s established precedent for this exact class of problem.
3. **Scope of every limit:** the poll ceiling is scoped per checkout attempt (a fresh click resets it), not per user or globally — mirrors `nextPollInterval`'s ref-reset-on-non-processing behavior exactly.
4. **Unbounded reads/writes:** none introduced. `createOrder`/`checkAccess` are both single-resource calls keyed by `lesson_id` — no list/range queries on the frontend.
5. **Inherited caps re-derived:** the 2s poll interval and 60s ceiling are new, not inherited — chosen deliberately at Razorpay's own confirmation timescale, explicitly NOT reusing `lessonStatusPoll.ts`'s 8s/20min constants, which are sized for a multi-minute LLM pipeline, not a payment webhook.
6. **Concurrent check-then-act safety:** **Corrected during review (Scale & Load Hunter, Edge Case Hunter) — the original "N/A on the frontend" answer was wrong.** `useRazorpayCheckout`'s `start()` had no guard against being invoked again while an attempt was already in flight — two rapid clicks, or the same lesson open in two tabs, both fired `create-order` before the first response landed and flipped the UI's `busy` flag, with no idempotency key in the request body to fall back on server-side either (the backend's own known gaps don't confirm one exists). Fixed: `start()` now no-ops unless `status` is `idle`/`error`/`timeout`, tested directly at the hook level (`useRazorpayCheckout.test.ts`, two synchronous `start()` calls in the same tick → exactly one `create-order`). Separately, the checkout.js script-load-exactly-once guarantee (AC-2) is NOT proven by any test in this story — it rests on Next.js's own documented `src`-dedup behavior (same trust level as `Turnstile.tsx`'s identical, also-untested reliance on it), not on a test that renders two button instances or unmocks `next/script` to check for a single script tag. The original claim that this was "covered by AC-6's test" was false; corrected here.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 6): `payment.service.ts` — `createOrder(lessonId)`, `checkAccess(lessonId)` (mocked per AC-4/D136), service-level tests.
- [x] Task 2 (AC: 2, 6): script-loading via `next/script` (`strategy="afterInteractive"`, matching `Turnstile.tsx`'s established convention — no custom script-loader needed since Next.js already dedupes by `src`).
- [x] Task 3 (AC: 2, 3, 4, 6): `useRazorpayCheckout` (state machine) + `RazorpayCheckoutButton.tsx` (thin UI wrapper) — click → create-order → open modal → handler → poll → redirect, plus all terminal/error states; component tests.
- [x] Task 4 (AC: 5, 6): guard test (`__tests__/guards/no-stripe-era-payment-routes.test.ts`) confirming no `amount_paise` sent, no dead Stripe-era route references anywhere in `apps/web/src`.
- [x] Task 5: registered **D136** in `docs/DEFECT-REGISTER.md`. Full `apps/web` suite (85 files, 1020 tests), `ruff`-equivalent (`pnpm lint`, 0 errors), and `pnpm type-check` all green.

## Dev Notes

### What NOT to do

- Do NOT build `/payment/success`, `/payment/cancel`, or any `create-checkout-session` call — Stripe-era, no backend counterpart (AC-5).
- Do NOT send `amount_paise` from the client to `create-order` — the server ignores it and always uses its own DB price; sending it implies a control the frontend doesn't have and invites confusion during review.
- Do NOT hardcode `checkout.razorpay.com`'s script URL anywhere but `RazorpayCheckoutButton.tsx`. **Corrected during review (Acceptance Auditor, Process Integrity, Story Quality) — this line originally said the Razorpay key comes from a `NEXT_PUBLIC_RAZORPAY_KEY_ID` env var; that was never true and no such env var exists anywhere in the diff.** The actual, correctly-implemented mechanism: the key comes from the backend's own `create-order` response (`order.key_id`, per AC-1) on every request — no client-side env var at all, which is arguably better (the backend controls which key is live without a frontend redeploy). Do not add a `NEXT_PUBLIC_RAZORPAY_KEY_ID` env var; there is nothing for it to do.
- Do NOT silently poll forever, and do NOT silently treat a poll-ceiling-hit as success — both are the exact "silent truncation" failure class CLAUDE.md forbids.
- Do NOT build the real `GET /api/payments/access` call as if it exists — it doesn't yet (confirmed by reading the branch directly). Mock it behind `payment.service.ts`, registered as D136, swappable later.

### Testing standards

Vitest + Testing Library, matching this repo's existing `apps/web/src/__tests__/` conventions. The Razorpay `checkout.js` global (`window.Razorpay`) is mocked in tests — no real script load, no real network call to Razorpay's own servers.

### References

- [Source: docs/dev2-sprint-tracker.md, S4-02] — origin of this task; its Stripe-shaped detail is superseded by this story.
- [Source: origin/razorpay-backend-endpoints-dev3, apps/api/app/modules/payments/{router,schemas,service}.py] — the real backend contract this story is grounded against, read directly rather than assumed from the cross-team message.
- [Source: apps/web/src/lib/lessonStatusPoll.ts] — the poll-with-ceiling pattern this story's access-poll reuses (interval/ceiling values differ, shape does not).
- [Source: apps/web/src/services/onboarding.service.ts] — the service-file shape `payment.service.ts` follows.
- [Source: docs/decisions/ADR-002-payment-gateway-razorpay.md] — the Stripe→Razorpay decision this story implements against.

## Dev Agent Record

### Implementation Plan

- **`useRazorpayCheckout` state machine** (`idle → creating_order → awaiting_payment → confirming → error|timeout`, plus `ondismiss` back to `idle`) owns all the logic; `RazorpayCheckoutButton.tsx` is a thin presentational wrapper, mirroring this repo's existing hook+component split (`useAttentionConsent`/`AttentionConsentModal`).
- **Script loading**: `next/script` with `strategy="afterInteractive"` and an `onReady` callback — the exact pattern already established by `Turnstile.tsx` for a different third-party widget. Next.js dedupes by `src` across mounts, so AC-2's "loaded exactly once" is a platform guarantee, not something this story needed to build.
- **Poll implementation**: initially wrote the recursive poll as a self-referencing `useCallback` (`pollAccess` scheduling `setTimeout(() => pollAccess(...))` inside its own body) — `eslint-plugin-react-hooks`'s `react-hooks/immutability` rule rejected this as an error (a `useCallback` body cannot reference its own not-yet-fully-declared binding for a recursive reschedule). Refactored to a plain module-level `schedulePoll()` function taking every dependency as a parameter instead of closing over hook state — same behavior, no self-reference, passes lint clean.
- **D136** (`docs/DEFECT-REGISTER.md`): `checkAccess()` is a hardcoded mock since `GET /api/payments/access` doesn't exist on the backend yet — confirmed directly by reading `origin/razorpay-backend-endpoints-dev3`'s `router.py`, not assumed from the cross-team message.

### Completion Notes

- All 5 tasks complete. Full `apps/web` suite: **85 files, 1020 tests passed**, zero failures (includes the 10 new tests this story adds). `pnpm lint`: 0 errors, 33 warnings total — one of those 33 is the intentionally-unused `_lessonId` mock parameter (documented inline via the D136 comment, not silent), the rest are pre-existing and unrelated to this story. `pnpm type-check`: clean.
- Grounded against the REAL backend branch (`origin/razorpay-backend-endpoints-dev3`), not just the cross-team integration message — this caught that the message's flow description was accurate, but let this story independently confirm (rather than assume) three load-bearing facts: the exact response field names, that `create-order` is `ApprovedUser`-gated today, and that no server-side minimum-price guard exists (all three inform the product-owner Q&A this story's kickoff also produced).
- `docs/dev2-sprint-tracker.md`'s S4-02 section still describes the old Stripe-shaped flow — not updated by this story (out of scope; the story doc itself is the current source of truth per this repo's own stated pattern of story docs sometimes superseding stale tracker prose).

### File List

- `apps/web/src/types/payment.ts` (NEW)
- `apps/web/src/services/payment.service.ts` (NEW)
- `apps/web/src/services/index.ts` (MODIFIED — export the new service)
- `apps/web/src/hooks/useRazorpayCheckout.ts` (NEW)
- `apps/web/src/components/payment/RazorpayCheckoutButton.tsx` (NEW)
- `apps/web/src/__tests__/services/payment.service.test.ts` (NEW — 3 tests)
- `apps/web/src/__tests__/components/payment/RazorpayCheckoutButton.test.tsx` (MODIFIED — review round: 7 tests, up from 6; added the script-load-failure test)
- `apps/web/src/__tests__/hooks/useRazorpayCheckout.test.ts` (NEW — review round: 5 tests covering re-entrancy, mid-poll rejection, unmount-during-poll, missing `window.Razorpay`)
- `apps/web/src/__tests__/guards/no-stripe-era-payment-routes.test.ts` (MODIFIED — review round: split into 2 tests, widened the `amount_paise` match from colon-only to a word boundary, narrowed the doc-comment exemption to only the `amount_paise` check instead of the whole file)
- `docs/DEFECT-REGISTER.md` (MODIFIED — registered D136)

## Senior Developer Review (AI)

**Date:** 2026-08-27
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers (8 layers, per CLAUDE.md's BMAD Code Review Gate, via the `bmad-code-review` skill):** Blind Hunter (diff-only, no project context), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec), Scale & Load Hunter (diff + repo access + `docs/SCALE-CONTRACT.md`), Story Quality, Test Coverage, AC Completeness, Process Integrity.

### Findings

| # | Severity | Source (layers agreeing) | Finding | Resolution |
|---|----------|---------------------------|---------|------------|
| 1 | **High** | Scale & Load Hunter, Edge Case Hunter | `start()` had no re-entrancy guard — two rapid clicks or the same lesson open in two tabs both fire `POST create-order` before the first response lands and flips the UI's `busy` flag; no idempotency key exists in the request body to fall back on. | Fixed — `start()` now no-ops unless `status` is `idle`/`error`/`timeout`. Tested directly at the hook level (two synchronous `start()` calls in the same tick → exactly one `create-order`), since the UI-level `disabled` guard alone doesn't close the race. |
| 2 | **High** | Blind Hunter, Edge Case Hunter, Scale & Load Hunter (3 layers) | `<Script>` had no `onError` — if `checkout.js` fails to load (ad-blocker, CDN outage), `scriptReady` never becomes true and the button stays disabled forever with zero visible feedback. Exactly the "silent truncation" class CLAUDE.md forbids. | Fixed — added `onError` setting a visible alert; tested (`scriptShouldFail` mock flag). |
| 3 | **Med** (documentation defect, corroborated 3×) | Acceptance Auditor, Process Integrity, Story Quality | Story Dev Notes claimed `NEXT_PUBLIC_RAZORPAY_KEY_ID is read from env, never inlined` — no such env var exists anywhere in the diff; the key actually comes from the backend's `create-order` response on every request (arguably a better design). | Fixed — corrected the Dev Notes to describe the real, correctly-implemented mechanism instead of a claim that was never true. |
| 4 | **Med**, corroborated 3× | Acceptance Auditor, Story Quality, Scale & Load Hunter | AC-4's mock description ("returns `{has_access: true}` after one poll tick") doesn't match the code — it resolves `true` unconditionally on the very first call; the poll loop's "not yet" branch is only ever exercised by tests that override the mock. | Fixed — corrected AC-4's wording to describe the mock's actual (simpler) behavior rather than complicate the mock to fake a delay it doesn't need. |
| 5 | **Med**, corroborated 3× (false-claim variant) | Test Coverage, AC Completeness, Story Quality | Scale & Load Q6 and the component docstring claimed the checkout.js "exactly once even if mounted/clicked more than once" guarantee was "covered by AC-6's test" — no test renders two button instances, clicks twice, or unmocks `next/script` to check for a single script tag. The guarantee rests entirely on Next.js's own documented dedup behavior (same trust level `Turnstile.tsx` already relies on, also untested there). | Corrected Q6's wording to state plainly that this is a trusted platform guarantee, not something this test suite proves — matches reality rather than overclaiming. Building a real dedup test would require un-mocking `next/script`, a bigger test-infra change; deferred as a fast-follow, not blocking, since the risk is shared with an already-accepted precedent elsewhere in the codebase. |
| 6 | **High** (Test Coverage explicitly recommended blocking merge without this) | Test Coverage | `checkAccess` rejecting mid-poll (not just resolving `false`) was completely untested — the real-world failure mode a student sees on a network blip during confirmation. | Fixed — new hook-level test (`useRazorpayCheckout.test.ts`) asserts the `error` state and message, and that `router.push` never fires. |
| 7 | **High** (Test Coverage explicitly recommended blocking merge without this) | Test Coverage | Unmounting mid-poll was untested — the `mountedRef`/`clearTimeout` cleanup guard existed in code but nothing proved it actually stops further polling or a post-unmount `router.push`. | Fixed — new hook-level test unmounts mid-poll, advances timers past the ceiling, and asserts no further `checkAccess` calls and no redirect. |
| 8 | Med | Test Coverage | `window.Razorpay` being unexpectedly missing at `start()`-time (script reported ready but the global was clobbered/never attached) was unreachable in the existing test setup (every test's `beforeEach` sets it unconditionally) and untested. | Fixed — new hook-level test deletes the global mid-setup and asserts the existing guard's error message, proving previously-dead-to-tests code. |
| 9 | Low, corroborated 2× | Acceptance Auditor, Test Coverage | The `amount_paise` guard regex (`amount_paise:`) only matched the object-literal colon form — would miss `amount_paise=`, bracket access, or shorthand property syntax. | Fixed — widened to a word-boundary match (`amount_paise\b`), split into its own test from the dead-routes check so the exemption for `payment.service.ts`'s doc comment no longer also skips that file's dead-route scan (a separate finding, below). |
| 10 | Low | Story Quality | The guard test's exemption for `payment.service.ts` was file-wide, silently also skipping the dead-Stripe-route scan for that file, not just the `amount_paise` prose mention it was meant for. | Fixed as part of #9's split — the exemption now applies only to the `amount_paise` test, not the dead-routes test. |
| 11 | Low | Story Quality | Completion Notes' lint-warning arithmetic didn't reconcile ("33 pre-existing... plus one new" implied 34 total against an actual `33 problems` run). | Fixed — corrected wording to state the real total (33) and that one of those 33 is the new, intentional warning. |
| — | Refuted | Blind Hunter | Claimed "no story file in the diff, mixing story creation with implementation" — false: the story-only commit (`8a45202`) was already merged into `sprint4-master` before this branch's implementation commit; Blind Hunter has no project context and couldn't see the full history. Independently confirmed correct by Process Integrity (`git log --follow`, story-only commit chronologically first). | Not actionable — reviewer artifact of running diff-only with no history access, not a real defect. |
| — | Refuted / not actionable | Blind Hunter | "Unbounded recursive filesystem scan in the guard test" (`walk(SRC_DIR)`). | Not actionable — identical pattern to the already-established `no-library-references.test.ts` guard elsewhere in this codebase; bounded by repo size, not user input, and not a request-path query the Scale Contract's Q4 is aimed at. |
| — | Deferred, not blocking | Blind Hunter, Edge Case Hunter | Payment identifiers (`razorpay_payment_id` etc.) are captured in the `handler` callback but never logged/persisted for support reference; no response-shape validation before constructing `new window.Razorpay(...)`; no check that the handler's `razorpay_order_id` matches the order just created; generic (not actionable) messaging on a 401/403 from the `ApprovedUser`-gated backend. | Deferred — reasonable hardening for a later pass, but out of scope for "kick off the frontend part" against a backend that isn't merged yet; none of these are reachable today since nothing imports this component into a real page. |
| — | Not actionable (binding rule 7, partial) | Process Integrity, Scale & Load Hunter | D136's mocked `checkAccess` has a register entry (binding rule 5 satisfied) but no CI mechanism that would fail specifically because the real endpoint shipped and the mock was left in place (binding rule 7). | Not actioned this round — the existing test would still break if a future edit touched `checkAccess` without updating its test (MSW's `onUnhandledRequest: 'error'` would catch an unmocked real call), which is a reactive, not proactive, guard. Building a proactive one (e.g. a scheduled check against the live OpenAPI schema) is disproportionate for a Low-severity, isolated, not-yet-wired-into-any-page mock; revisit if this component gets wired into a real route before the backend endpoint ships. |

### Non-issues independently re-verified

- Sprint Task Branch Rule and Story-First Gate: branch correctly forked from `sprint4-master` (not `main`, not stacked on another task branch), story-only commit (`8a45202`) chronologically first, no commit mixes story creation with implementation code (Process Integrity, via direct `git log`/`git merge-base` inspection).
- No hardcoded secrets or scope creep: the only Razorpay-related literal is the public `checkout.js` CDN URL; zero touched files outside `apps/web/src/{hooks,components,services,types}/payment*`, its tests, and `docs/` (Process Integrity).
- Field names, `ApprovedUser` gating, absence of `GET /api/payments/access`, and the server-side `amount_paise`-ignore behavior were all independently re-confirmed against `origin/razorpay-backend-endpoints-dev3` rather than taken on the story's word (Story Quality).
- No mock-only-assertion (binding rule 2) violations found — every test assertion reviewed checks a real DOM/text outcome or the argument mapping onto an external-boundary mock (Razorpay's `window.Razorpay`, `router.push`), the correct way to test a browser-boundary integration point (Test Coverage).

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-26 | Story created after reading the real (unmerged) Razorpay backend branch directly (`origin/razorpay-backend-endpoints-dev3`) rather than trusting the cross-team integration message alone — confirmed the exact response shape, confirmed `create-order` is `ApprovedUser`-gated today (informs the product-owner Q1 answer), confirmed `GET /api/payments/access` does not exist yet (D136), and confirmed no server-side minimum-price guard exists (informs the Q2 pricing blocker being real, not hypothetical). Supersedes the stale Stripe-shaped S4-02 write-up in `docs/dev2-sprint-tracker.md`. Branch `sprint4/s4-02-razorpay-checkout` off `sprint4-master`. | Dev 2 |
| 2026-08-26 | Implemented all 5 tasks: `payment.service.ts`, `useRazorpayCheckout` state machine, `RazorpayCheckoutButton.tsx`, 10 new tests (service + component + guard), D136 registered. One implementation-time lint fix: the poll's recursive `useCallback` self-reference was rejected by `react-hooks/immutability` — refactored to a plain module-level `schedulePoll()` function. Full `apps/web` suite green (85 files, 1020 tests), lint 0 errors, typecheck clean. Not yet merged into `sprint4-master` — held pending the user's call on whether to fold this into the already-open, already-under-review PR #156, or open a separate PR, since 3 reviewers currently have #156 open. | Dev 2 |
