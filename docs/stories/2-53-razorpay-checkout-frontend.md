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
4. **AC-4 (mocked access check, explicitly flagged, not silently faked)** — `GET /api/payments/access` does not exist on the backend yet (confirmed above, independently of the cross-team message). Per that message's own guidance, this story builds against a **clearly labeled mock** (`checkAccess` in `payment.service.ts` returns `{has_access: true}` after one poll tick) so the UI flow (button → modal → poll → redirect) is fully buildable and testable now. This is registered as **D136** (`docs/DEFECT-REGISTER.md`, binding rule 5 — a documented limitation must carry a register ID, not just a code comment) with an explicit swap-out task once the real endpoint lands. The mock must be isolated behind the same `payment.service.ts` function signature the real call will use, so swapping it is a one-function change, not a component rewrite.
5. **AC-5 (no dead Stripe-era routes)** — Per the cross-team message, do NOT build `/payment/success`, `/payment/cancel`, or a `create-checkout-session` call — those are Stripe-shaped and have no backend counterpart on the real branch. The lesson player redirect (AC-3) is the only "success" surface; a failed/abandoned Razorpay modal (closed without paying) simply returns the button to its pre-click state, no dedicated cancel page.
6. **AC-6 (tests)** — Component tests for: successful create-order → modal open (mocking the `Razorpay` global), create-order failure (404 and 500) surfacing a visible error, the access-poll reaching `has_access: true` and redirecting, and the poll ceiling being hit (surfaced, not silent). Service tests for `payment.service.ts`'s `createOrder`/`checkAccess` request shapes. A guard test confirming the client never sends `amount_paise` (AC-1's price-integrity note) and never references any of the AC-5 dead routes.

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** one checkout attempt, per (user, lesson) pair. A student may retry after a failed/abandoned payment — the component must support being clicked again after any terminal state (error, poll-ceiling-hit), not just the happy path once.
2. **Fixed budgets vs. variable input:** the access-poll ceiling is the only new fixed budget this story introduces. Set to **60 seconds** (30 attempts at the 2s interval from the cross-team spec) — Razorpay's own webhook delivery is typically sub-second to a few seconds; 60s is generous headroom for webhook queueing/retry delay without leaving a student staring at a spinner indefinitely. Past the ceiling: explicit "taking longer than expected" state (never silent), matching `lessonStatusPoll.ts`'s established precedent for this exact class of problem.
3. **Scope of every limit:** the poll ceiling is scoped per checkout attempt (a fresh click resets it), not per user or globally — mirrors `nextPollInterval`'s ref-reset-on-non-processing behavior exactly.
4. **Unbounded reads/writes:** none introduced. `createOrder`/`checkAccess` are both single-resource calls keyed by `lesson_id` — no list/range queries on the frontend.
5. **Inherited caps re-derived:** the 2s poll interval and 60s ceiling are new, not inherited — chosen deliberately at Razorpay's own confirmation timescale, explicitly NOT reusing `lessonStatusPoll.ts`'s 8s/20min constants, which are sized for a multi-minute LLM pipeline, not a payment webhook.
6. **Concurrent check-then-act safety:** N/A on the frontend — the actual idempotency/concurrency boundary (duplicate webhook delivery, concurrent create-order calls) is entirely server-side (Story 4-1's own `lesson_access` write path). The frontend's only concurrency concern is UI-level: the checkout.js script-load guard (AC-2) must not double-inject the script if the button is clicked or mounted more than once — covered by AC-6's test.

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
- Do NOT hardcode `checkout.razorpay.com`'s script URL or the Razorpay key anywhere but this story's own files — `NEXT_PUBLIC_RAZORPAY_KEY_ID` is read from env, never inlined.
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

- All 5 tasks complete. Full `apps/web` suite: **85 files, 1020 tests passed**, zero failures (includes the 10 new tests this story adds). `pnpm lint`: 0 errors (33 pre-existing warnings, unrelated to this story, plus one new warning on the intentionally-unused `_lessonId` mock parameter — documented inline via the D136 comment, not silent). `pnpm type-check`: clean.
- Grounded against the REAL backend branch (`origin/razorpay-backend-endpoints-dev3`), not just the cross-team integration message — this caught that the message's flow description was accurate, but let this story independently confirm (rather than assume) three load-bearing facts: the exact response field names, that `create-order` is `ApprovedUser`-gated today, and that no server-side minimum-price guard exists (all three inform the product-owner Q&A this story's kickoff also produced).
- `docs/dev2-sprint-tracker.md`'s S4-02 section still describes the old Stripe-shaped flow — not updated by this story (out of scope; the story doc itself is the current source of truth per this repo's own stated pattern of story docs sometimes superseding stale tracker prose).

### File List

- `apps/web/src/types/payment.ts` (NEW)
- `apps/web/src/services/payment.service.ts` (NEW)
- `apps/web/src/services/index.ts` (MODIFIED — export the new service)
- `apps/web/src/hooks/useRazorpayCheckout.ts` (NEW)
- `apps/web/src/components/payment/RazorpayCheckoutButton.tsx` (NEW)
- `apps/web/src/__tests__/services/payment.service.test.ts` (NEW — 3 tests)
- `apps/web/src/__tests__/components/payment/RazorpayCheckoutButton.test.tsx` (NEW — 6 tests)
- `apps/web/src/__tests__/guards/no-stripe-era-payment-routes.test.ts` (NEW — 1 test)
- `docs/DEFECT-REGISTER.md` (MODIFIED — registered D136)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-26 | Story created after reading the real (unmerged) Razorpay backend branch directly (`origin/razorpay-backend-endpoints-dev3`) rather than trusting the cross-team integration message alone — confirmed the exact response shape, confirmed `create-order` is `ApprovedUser`-gated today (informs the product-owner Q1 answer), confirmed `GET /api/payments/access` does not exist yet (D136), and confirmed no server-side minimum-price guard exists (informs the Q2 pricing blocker being real, not hypothetical). Supersedes the stale Stripe-shaped S4-02 write-up in `docs/dev2-sprint-tracker.md`. Branch `sprint4/s4-02-razorpay-checkout` off `sprint4-master`. | Dev 2 |
| 2026-08-26 | Implemented all 5 tasks: `payment.service.ts`, `useRazorpayCheckout` state machine, `RazorpayCheckoutButton.tsx`, 10 new tests (service + component + guard), D136 registered. One implementation-time lint fix: the poll's recursive `useCallback` self-reference was rejected by `react-hooks/immutability` — refactored to a plain module-level `schedulePoll()` function. Full `apps/web` suite green (85 files, 1020 tests), lint 0 errors, typecheck clean. Not yet merged into `sprint4-master` — held pending the user's call on whether to fold this into the already-open, already-under-review PR #156, or open a separate PR, since 3 reviewers currently have #156 open. | Dev 2 |
