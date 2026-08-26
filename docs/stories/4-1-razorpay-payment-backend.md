---
baseline_commit: 65459565aac7c660f7bb4dd40e447f6a7ccd2c91
---

# Story 4.1: Razorpay Payment Backend — Order Creation & Webhook Fulfillment

Status: in-progress

## Story

As a student who has selected a lesson to purchase,
I want the platform to create a Razorpay payment order and confirm my access only after
payment is verified server-side,
so that I can pay via UPI/wallet (India-first) and get access to my lesson without
any risk of spoofed client-side success callbacks.

**Context:** Stripe has been removed from the spec. Razorpay replaces it as the payment
gateway (ADR-002, India-first, UPI/wallet support). Dev 3 owns the backend (FastAPI).
Dev 2 owns the frontend (`RazorpayCheckoutButton.tsx`, `/payment/success`, `/payment/cancel`).
This story covers the backend only. Dev 2 is building against the frozen response contract
defined in AC-1.

**Source:** Manager's spec message (2026-08-26) for S4-3 backend scope.

## Acceptance Criteria

1. **AC-1 (create-order endpoint)** — `POST /api/payments/create-order` (authenticated,
   `ApprovedUser` dependency) calls Razorpay's Orders API and returns exactly
   `{ "order_id": "<razorpay_order_id>", "key_id": "<RAZORPAY_KEY_ID>" }`. The response
   NEVER includes `RAZORPAY_KEY_SECRET` or `RAZORPAY_WEBHOOK_SECRET`. Request body:
   `{ "lesson_id": "<uuid>", "amount_paise": <int> }` (amount in smallest currency unit).

2. **AC-2 (webhook endpoint)** — `POST /api/payments/webhook` (no auth — Razorpay calls it
   directly) reads the raw request body bytes BEFORE any JSON parsing, verifies the
   `X-Razorpay-Signature` header as HMAC-SHA256 over those raw bytes using
   `hmac.compare_digest`. A missing or invalid signature returns HTTP 400 immediately.
   The raw bytes are NEVER re-serialized before hashing (re-serializing breaks key
   ordering and whitespace, which is the most common Razorpay integration bug).

3. **AC-3 (payment.captured fulfillment)** — On a verified `payment.captured` event,
   the handler writes one row to `lesson_access` with
   `(user_id, lesson_id, razorpay_payment_id, razorpay_order_id, amount_paise, currency,
   status='captured')`. Other event types (`payment.failed`, `refund.*`, etc.) are
   acknowledged with 200 and ignored.

4. **AC-4 (idempotency via DB constraint)** — `lesson_access.razorpay_payment_id` has a
   `UNIQUE` constraint at the DB level (not just app-level). When Razorpay redelivers the
   same webhook (it retries on non-200), the second call catches the unique_violation
   (PostgreSQL error 23505) and returns 200 without double-crediting. No SELECT-then-INSERT
   race (same class as D45).

5. **AC-5 (provider abstraction)** — All Razorpay HTTP calls live in
   `apps/api/app/providers/payments/razorpay.py` as `RazorpayProvider`. Business logic in
   `service.py` never calls `httpx` directly. HMAC verification logic lives in the provider,
   not the router.

6. **AC-6 (env vars in Settings)** — Three new fields in `apps/api/app/config.py`:
   `razorpay_key_id: str`, `razorpay_key_secret: str`, `razorpay_webhook_secret: str`.
   All three use `Field(...)` (required). Only `razorpay_key_id` ever leaves the server
   (in the `create-order` response). The other two are never logged or returned.

7. **AC-7 (new migration)** — `supabase/migrations/20260826000000_razorpay_payments.sql`
   creates `public.lesson_access` with columns: `id uuid PK`, `user_id uuid FK users`,
   `lesson_id uuid FK lessons`, `razorpay_payment_id text NOT NULL UNIQUE`,
   `razorpay_order_id text NOT NULL`, `amount_paise integer NOT NULL`,
   `currency text NOT NULL DEFAULT 'INR'`, `status text NOT NULL DEFAULT 'captured'`,
   `created_at timestamptz NOT NULL DEFAULT now()`. RLS: users read only their own rows.

8. **AC-8 (tests)** — Unit tests in `apps/api/tests/test_razorpay_payments.py` cover:
   valid signature accepted (200), invalid signature rejected (400), raw-bytes hashing
   (not re-serialized JSON), idempotent duplicate webhook returns 200, create-order
   response shape, response never contains secret key, `payment.captured` writes
   `lesson_access` row, non-captured events ignored gracefully.

## Tasks

- [ ] 1. Write failing tests (`test_razorpay_payments.py`) — RED phase
- [ ] 2. Write migration `20260826000000_razorpay_payments.sql`
- [ ] 3. Add `razorpay_key_id`, `razorpay_key_secret`, `razorpay_webhook_secret` to `config.py`
- [ ] 4. Create `providers/payments/razorpay.py` (`RazorpayProvider`) with `create_order()` and
         `verify_signature()` methods using `httpx.AsyncClient` and `hmac`
- [ ] 5. Create `modules/payments/schemas.py` (request/response Pydantic models)
- [ ] 6. Create `modules/payments/service.py` (`handle_payment_captured`, `create_order`)
- [ ] 7. Create `modules/payments/router.py` (two endpoints, raw body for webhook)
- [ ] 8. Register payments router in `main.py` at `/api/payments`
- [ ] 9. Run tests — GREEN phase; confirm all 8 AC tests pass
- [ ] 10. Run ruff + mypy; zero violations

### Review Findings

- [ ] [Review][Patch] Price and lesson ownership not validated server-side — Any authenticated user can pass `amount_paise=1` and any `lesson_id` (including another user's lesson or a premium lesson) to `create-order`. The server trusts the client-supplied values without checking the lesson's canonical price or ownership. After a real payment, the webhook grants lesson access regardless of price mismatch — an authenticated user can pay the minimum and access any lesson. Fix: look up the lesson's actual `price_paise` server-side and use that value for the Razorpay order; validate `lesson_id` belongs to (or is purchasable by) the requesting user. [apps/api/app/modules/payments/router.py:42]
- [ ] [Review][Patch] Service idempotency catch (23505) is a MOCK-CONTRACT — untested real path — `test_duplicate_webhook_both_return_200` mocks `handle_payment_captured` entirely; the actual exception-catch-and-return logic in `service.py:95–106` has no test. Per DEFECT-REGISTER binding rule 2, a test may not assert only on a mock it constructed. Add a direct unit test for `handle_payment_captured` that supplies a mock Supabase client raising a 23505-matching exception and verifies the function returns cleanly without re-raising. [apps/api/tests/test_razorpay_payments.py:259]
- [ ] [Review][Patch][Scale] FK violation on invalid lesson_id = silent money loss (SCALE Q2 silent-wrong-result) — If `lesson_id` in webhook notes refers to a deleted or nonexistent lesson, the INSERT hits a PG FK violation (error 23503, NOT caught by the 23505 handler). Service re-raises → webhook 500 → Razorpay retries ~15× → permanently discards → student paid, access never granted, no admin alert. Per SCALE-CONTRACT Q2 and `step-03-triage.md` rules, silent-wrong-result may NEVER be classified defer. Fix: pre-validate `lesson_id` exists in `lessons` table before INSERT; emit `logger.critical` + Sentry alert if the FK violation fires anyway. [apps/api/app/modules/payments/service.py:90]
- [x] [Review][Defer] Sync supabase call blocks event loop [apps/api/app/modules/payments/service.py:90] — deferred, pre-existing — `supabase.table(...).insert(...).execute()` is synchronous inside `async def handle_payment_captured`. Pre-existing pattern shared by all service modules (`assessment/service.py`, `analytics/service.py`); must be fixed project-wide in a dedicated async-supabase refactor story. Tracked as DEFER-017.

## Scale & Load

1. **One unit of work and its range** — one `POST /api/payments/create-order` call =
   one HTTP call to Razorpay API (~200–800 ms). One webhook delivery = one DB INSERT.
   Max concurrent: bounded by Railway instance count × FastAPI worker threads.

2. **Fixed budgets vs. variable input** — Razorpay `amount_paise` is validated as `int`
   in the request schema (Pydantic rejects non-integers). No unbounded input path.

3. **Scope of every limit** — per-request; no shared state except the DB UNIQUE constraint
   (cluster-wide, correct). `RAZORPAY_KEY_SECRET` is per-deployment (env var, not per-user).

4. **Unbounded reads and writes** — `lesson_access` INSERT is a single row write bounded
   by the UNIQUE constraint. No SELECT loop. No batch operation.

5. **Inherited caps re-derived** — no cap inherited. `httpx.AsyncClient` uses a per-request
   timeout (set explicitly to 10s in provider, not the default infinite). Razorpay webhook
   redelivery retries up to ~15 times — idempotency handles all retries safely.

6. **Check-then-act concurrency** — idempotency is enforced by the DB UNIQUE constraint,
   not app-level SELECT-then-INSERT. Concurrent redeliveries both attempt INSERT; one
   succeeds, the other catches 23505 and returns 200. No race.

## Dev Notes

- **HMAC raw bytes**: `body = await request.body()` BEFORE `await request.json()`.
  Never pass `json.dumps(await request.json())` to the HMAC — key ordering is not
  guaranteed to match what Razorpay signed.
- **httpx for Razorpay API calls** — async-native, already in the dependency tree
  (used by `providers/llm/openai.py`). Do NOT add the `razorpay` PyPI package (sync SDK).
- **Webhook endpoint has no `ApprovedUser` dependency** — Razorpay calls it, not the student.
  Auth is the HMAC signature check only.
- **Razorpay Orders API**: `POST https://api.razorpay.com/v1/orders` with Basic Auth
  (`RAZORPAY_KEY_ID:RAZORPAY_KEY_SECRET`). Returns `{"id": "order_xxx", ...}`.
- **Unique constraint name**: `lesson_access_razorpay_payment_id_key` — must match exactly
  what PostgreSQL auto-names a `UNIQUE` column constraint, so the 23505 handler can be
  tested without relying on the constraint name string directly.
- **user_id in webhook**: `payment.captured` payload contains `notes.user_id` — Dev 2
  must pass `user_id` as a Razorpay order note when creating the order from the frontend
  (or alternatively, Dev 3 looks up `user_id` from the `order_id` in `lesson_access`).
  Simplest: store `user_id` in Razorpay order notes at creation time (AC-1 request body
  includes it, or derive from the JWT).

## Dev Agent Record

### Completion Notes
(filled in after implementation)

### File List
(filled in after implementation)
