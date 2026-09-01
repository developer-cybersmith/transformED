# ADR-002 — Payment gateway: Razorpay replaces Stripe

**Status:** 🟢 **DECIDED** — provider and integration shape are settled; endpoint implementation is still Sprint 4 S4-3 (Dev 1) / S4-02 (Dev 2), not yet built
**Date:** 2026-08-24 · **Owner:** Dev 1 (backend order/webhook), Dev 2 (checkout UI + return pages)
**Supersedes:** every prior "Stripe Checkout (hosted)" reference in `CLAUDE.md`, `docs/master-tracker.md`, `docs/dev1-tracker.md`, `docs/dev2-sprint-tracker.md`, `docs/dev2-frontend-role.md`, `docs/bmad/epics/epic-5-platform-core.md`.
**Referenced by:** `docs/bmad/epics/epic-5-platform-core.md` §Payments, `docs/dev1-tracker.md` S4-3, `docs/dev2-sprint-tracker.md` S4-02

---

## Decision

Use **Razorpay** as the sole payment gateway for MVP (per-lesson credit purchases). Stripe is
removed from every tracker/spec — there is no dual-provider period and no Stripe code has been
written yet, so this is a clean swap, not a migration of live data.

## Why

- **UPI is the dominant payment method for the target Indian student market**, and Stripe's
  standard India integration doesn't natively support it — Razorpay's checkout dynamically
  surfaces UPI/wallets/netbanking alongside cards.
- Consistent with the already-decided India-region direction (`ADR-001`, CLAUDE.md §Security/§Dev
  rules: Supabase data residency in `ap-south-1`, FastAPI/ARQ migrating to an India region before
  Sprint 3 real students). A payment gateway with no India rail is the odd piece out otherwise.
- Razorpay's 0% MDR on UPI transactions under ₹2,000 (NPCI waiver) matters directly against the
  CLAUDE.md `$3.00/lesson` cost-ceiling mindset — Stripe's card-only India processing has no
  equivalent for a low-ticket-price product.
- Trade-off accepted knowingly: Stripe Billing has stronger subscription/complex-pricing support.
  Not relevant here — CLAUDE.md's payments scope is per-lesson credits only; subscriptions are
  explicitly Out of Scope (Phase 2) in `epic-5-platform-core.md`.

## What changes from the Stripe-shaped spec

The old spec assumed a **full-page redirect** hosted checkout (`stripe.com` → success/cancel
redirect URLs). Razorpay Standard Checkout is a **JS-embedded overlay** (`checkout.js`), not a
page redirect. The security property CLAUDE.md actually cares about — *card data never touches
our servers* — holds either way, since Razorpay's overlay is its own PCI-compliant iframe. But two
things genuinely change:

1. **Success is a client-side callback, not a redirect.** `/payment/success` must be treated as
   optimistic UX only. The backend must never grant `lesson_access` from that callback — **only
   the signature-verified webhook (`payment.captured`) is trusted**, because the browser callback
   can be spoofed client-side or never fire if the tab closes mid-payment.
2. **No `stripe-signature`-style SDK helper exists for Python.** Razorpay's Python SDK
   (`razorpay-python`) has no built-in FastAPI/webhook-body helper — verification is a manual
   HMAC-SHA256 over the **raw** request body (not re-serialized JSON) compared in constant time
   against `RAZORPAY_WEBHOOK_SECRET`. Getting this wrong (parsing then re-dumping JSON before
   hashing) is the single most common Razorpay webhook bug reported in the wild — the hash won't
   match because key ordering/whitespace differs from what Razorpay signed.

## Integration architecture

**Backend (Dev 1, `apps/api/app/modules/...` — not touched by this ADR, scoping only):**
- `POST /api/payments/create-order` — calls Razorpay Orders API (`client.order.create`), returns
  `order_id` + `key_id` (publishable) to the frontend. Never returns the key *secret*.
- `POST /api/payments/webhook` — reads the **raw** body + `X-Razorpay-Signature` header, verifies
  via `hmac.new(secret, raw_body, sha256).hexdigest()` compared with `hmac.compare_digest`, handles
  `payment.captured` (credit `lesson_access`) and `payment.failed` (log only). Idempotent on
  `razorpay_payment_id` — needs a UNIQUE constraint backing the check, not just an app-level
  pre-check (same class of gap as **D45** in the Defect Register — a check-then-act race under
  concurrent webhook redelivery).
- New table `razorpay_events` (or reuse `lesson_access` with a `razorpay_payment_id` column) —
  replaces the old `stripe_events` migration reference.
- Env vars: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (Railway/target
  India-region provider, per ADR-001 — never in `NEXT_PUBLIC_*`).

**Frontend (Dev 2, `apps/web`):**
- `RazorpayCheckoutButton.tsx` — loads `https://checkout.razorpay.com/v1/checkout.js` (Razorpay's
  own hosted script; not a party to CLAUDE.md's "no card data on our servers" rule since it's
  Razorpay's own script, but still worth pinning/reviewing since it's third-party JS on the
  payment page), calls `create-order`, opens the overlay with `key_id` + `order_id`, and only
  `NEXT_PUBLIC_RAZORPAY_KEY_ID` (publishable) ever reaches the browser.
- `src/app/payment/success/page.tsx` / `.../cancel/page.tsx` — unchanged in shape from the Stripe
  plan, just reached via client-side navigation after the `handler` callback instead of a
  server redirect.
- On success, poll/refetch `lesson_access` (SWR) rather than trusting the URL params for credit
  count — the webhook may not have landed yet when the success page mounts.

## Scale & Load (CLAUDE.md six questions, abbreviated — full pass belongs in the S4-3/S4-02 story files)

1. **Unit of work:** one checkout = one Razorpay Order = one `lesson_access` credit grant.
2. **Fixed budget vs. variable input:** webhook retries are Razorpay-driven (bounded by their
   retry schedule, not ours) — no unbounded retry loop on our side.
3. **Scope:** `lesson_access` is per-user; idempotency key (`razorpay_payment_id`) must be globally
   unique, not per-user, since a replayed webhook has the same payment ID regardless of who's
   asking.
4. **Unbounded reads/writes:** none introduced — this is a single-row upsert per payment.
5. **Inherited caps:** none carried over from the Stripe plan; this is a fresh design.
6. **Concurrent check-then-act:** the idempotency check on `razorpay_payment_id` **must** be
   backed by a DB-level UNIQUE constraint, not just an app-level `SELECT` then `INSERT` — flagging
   this now so S4-3's story doesn't repeat D45.

## Open items (not resolved by this ADR — belong in the S4-3/S4-02 stories)

- Exact schema for the `razorpay_events`/idempotency table.
- Whether `/payment/success` shows a spinner-then-resolve state while waiting for the webhook, or
  optimistic success immediately (UX call, not architecture).
- Razorpay account provisioning (live + test mode keys, webhook URL registered in the Razorpay
  dashboard) — ops task, blocks any real end-to-end test.
