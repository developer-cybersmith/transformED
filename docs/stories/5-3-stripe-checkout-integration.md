# Story 5-3 — Stripe Checkout integration (hosted page, not custom UI)

Status: review

## Story

As a **student**,
I want to buy lesson credits through Stripe's hosted Checkout page and have my access unlocked automatically the moment payment succeeds,
so that I can pay for lessons without my card details ever touching TransformED's servers, and without a developer having to manually grant me access.

## Acceptance Criteria

1. `POST /api/payments/create-checkout-session` (authenticated, `CurrentUser`/JWT required — 401 without a valid bearer token) creates a Stripe Checkout Session in `mode="payment"` for the single Phase-1 lesson-credit product, embeds `metadata={"user_id": <JWT sub>}` on the session, and returns `{checkout_url, session_id}`. The endpoint never accepts a client-supplied price or amount — the Price ID is a server-side config value.
2. The Checkout Session's `success_url`/`cancel_url` point at the frontend routes Dev 2 owns (`/payment/success?session_id={CHECKOUT_SESSION_ID}`, `/payment/cancel`) — this story only sets those URLs; the pages themselves are out of scope (see Cross-Team Note below).
3. `POST /api/payments/webhook` reads the **raw** request body (before any JSON parsing) and verifies the `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET`. A missing or invalid signature returns `400` and writes nothing to any table — no `stripe_events` row, no `lesson_access` row.
4. On a signature-verified `checkout.session.completed` event, exactly one `lesson_access` row exists for the paying user afterward, with `lesson_credits` incremented by the configured per-purchase amount, applied through an atomic DB-side upsert (never a Python read-modify-write).
5. Webhook idempotency: redelivering the **same** Stripe event id (`evt_...`) — Stripe's own documented retry behavior on anything but a `2xx` — does not grant a second credit. Enforced by a durable `UNIQUE`/primary-key constraint in Postgres, not an in-process cache or a SELECT-then-INSERT check.
6. Stripe event types other than `checkout.session.completed` (e.g. `payment_intent.created`) are acknowledged with `200` and produce no `lesson_access` write — an unhandled-but-valid event is a no-op, not an error, so Stripe does not retry it forever.
7. `lesson_access` has Row Level Security enabled; the only policy for `authenticated`/`anon` is `SELECT ... WHERE user_id = auth.uid()`. There is no `INSERT`/`UPDATE`/`DELETE` policy for either role — every write happens server-side via the service-role client, so a student can never grant themselves credits by writing their own row.
8. `POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons` (the real lesson-generation/spend endpoint — see Project Structure Notes for why this is not `POST /api/content/lessons`) rejects a request with `402 Payment Required` when the caller's `lesson_credits <= 0`, **before** any `lessons` row, `lesson_jobs` row, or ARQ job is created. No partial state is left behind on a 402.
9. On the same endpoint, a request that creates a genuinely new lesson (not the existing idempotent 200-replay-of-an-existing-lesson path) atomically decrements `lesson_credits` by exactly 1 via a conditional DB-side `UPDATE ... WHERE lesson_credits > 0`, never a Python check-then-write. A request that hits the existing idempotent replay branch (Gate 5, matching `generating`/`ready` lesson) does **not** spend a second credit.
10. `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are real, required fields on `Settings` (`apps/api/app/config.py`) — no bare `os.environ.get("STRIPE_...")` anywhere in business logic — and all Stripe SDK calls are made through a `providers/payments/` wrapper, never `import stripe` inside a router or service module.
11. If a downstream failure occurs after the credit decrement (AC 9) but before the ARQ job is confirmed enqueued, the spent credit is refunded (mirrors the existing rollback branches already in `generate_chapter_lesson`) — a platform-side failure must never cost the student a credit they received nothing for.

## Scale & Load

<!-- REQUIRED — see docs/SCALE-CONTRACT.md. Answer all six BEFORE writing Tasks/Subtasks.
     "N/A" is valid ONLY with a stated reason. A bare "N/A" is a missing answer. -->

1. **What is ONE unit of work, and what is its range?**
   Three distinct units, all small and fixed-shape (unlike the pipeline's book-scale problem):
   (a) one Checkout Session creation request — a single small JSON call to Stripe, no user-controlled size axis at all (no file, no page count); (b) one webhook delivery — a single Stripe event object, whose shape and size are controlled by Stripe, not by our users, and are small regardless of how large a purchase is (Stripe's `checkout.session.completed` payload is a fixed schema); (c) one credit spend at lesson-generation time — a single-row conditional UPDATE. There is no "min/typical/largest" axis analogous to page count here because none of these three units scales with anything a student uploads. The one real range to state: credits-per-purchase is presently undecided as a *product* number (Phase 1 pricing is "single tier, per-lesson credit model" per `docs/bmad/epics/epic-5-platform-core.md` — no concrete price or credit count is fixed anywhere in the repo). This story treats it as a server-side config constant (`stripe_lesson_credits_per_purchase`), not a value parsed out of the Stripe payload, specifically so a pricing decision later is an env-var change, not a code change.

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   - Credits granted per completed checkout = a fixed config constant, deliberately **not** derived from `amount_total` on the Stripe session. If this were derived from the payment amount instead, a Stripe-side product/price misconfiguration could silently grant the wrong number of credits with no error — computing credits from a fixed, server-controlled Price ID instead of a payload-supplied amount is the explicit, surfaced-degradation-free choice here.
   - The webhook body is read raw (`await request.body()`) with no explicit max-size guard in this story. Stripe's `checkout.session.completed` payload is small and fixed-schema, so this is accepted as naturally bounded by the sender (Stripe), not by us — but this bound is Stripe's contract, not ours to enforce, and should be revisited if Stripe webhooks ever start embedding large object expansions.
   - A malformed/unexpected event body (missing `metadata.user_id` on a `checkout.session.completed` event) must **not** silently 200-and-drop *and* must not throw an uncaught 500 that causes Stripe to retry forever: it is logged at ERROR/Sentry severity and acknowledged 200 (so Stripe's retry queue does not hammer a payload that will never parse differently), with the gap surfaced to an operator, not merely a `logger.warning` nobody reads.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   - `lesson_credits`: **per user** (one `lesson_access` row per `user_id`, primary-keyed on `user_id`).
   - `stripe_events` idempotency ledger: **per deployment** — one shared Postgres table for the whole Supabase project, so idempotency is correct regardless of which API replica receives the webhook. This is a deliberate contrast with D49 (`RATE_LIMIT_STORAGE_URL` defaulting to `memory://`, multiplying every rate-limit ceiling by replica count): the idempotency guarantee here is a durable Postgres `UNIQUE` constraint from day one, not in-process state, so it does not have a D49-shaped failure mode to inherit.
   - Per-user rate limit on `create-checkout-session`: must be keyed by JWT `sub` (reusing `_get_user_key`/`limiter` from `apps/api/app/core/rate_limit.py`, the same fix already validated for D52/D64), **not** by IP — an IP-keyed limiter on a payment endpoint would repeat D52's bucket-sharing bug in a context where it blocks someone from paying.
   - The webhook endpoint itself carries **no** per-user rate limit at all (it has no `CurrentUser` — Stripe is the caller) and must be explicitly exempted from any IP-based app-wide limiter (`main.py`'s IP-keyed limiter), since a burst of legitimate Stripe retries from Stripe's own IP ranges must never be throttled.
   - `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`: **per deployment**, one key pair, same scope as `supabase_service_role_key`.

4. **Which reads and writes are UNBOUNDED?**
   None, by construction, and this is the one axis where this story is structurally lower-risk than the content pipeline's history (D50, D59, D115 — all full-table or growing-without-bound reads on request paths). Every read/write this story adds is a single-row lookup keyed by a unique or primary key: the webhook's idempotency check is `.eq("stripe_event_id", ...).maybe_single()` (at most 1 row); the credit-grant and credit-spend operations are both single-row DB-side UPDATE/UPSERT RPCs scoped to one `user_id`; the generation-gate credit check is a `.eq("user_id", ...)` lookup on a table that is, by schema, exactly one row per user. Nothing in this story enumerates rows across users or across a user's history.

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   None — confirmed by a repo-wide search: zero `stripe` references anywhere under `apps/api` or `apps/web`, and no `lesson_access`/`stripe_events` table in any of the fourteen files under `supabase/migrations/`. This is greenfield; there is nothing to re-derive. The one thing genuinely reused rather than re-derived from scratch is the per-user rate-limit key function (`_get_user_key`) — deliberately, because writing a second, independent JWT-decode-for-rate-limiting from scratch is exactly how D64 reintroduced D52's bug the first time (a second decoder drifting out of sync with `dependencies.get_current_user`'s algorithm handling). Reuse here is a considered choice, not the "matches existing accepted pattern" ratchet CLAUDE.md's binding rule 6 warns against — it is the same code path, not merely the same shape.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   Three check-then-act sequences in this story, each closed at the database level rather than in Python:
   - **Webhook idempotency.** Two concurrent (or Stripe-redelivered) deliveries of the same event: both attempt `INSERT INTO stripe_events (stripe_event_id, ...) ... ON CONFLICT (stripe_event_id) DO NOTHING`. Only one insert actually affects a row; the credit grant proceeds **only** for the request whose insert affected a row (checked via the RPC/insert's own returned row count, never a prior `SELECT` that a second request could race past).
   - **Credit grant.** `grant_lesson_credits(user_id, credits)` is an atomic `INSERT ... ON CONFLICT (user_id) DO UPDATE SET lesson_credits = lesson_access.lesson_credits + excluded.lesson_credits` inside a single statement (mirrors the existing `increment_learner_dna_session_count` RPC in `supabase/migrations/20260813000001_dna_session_count_atomic_increment.sql`) — safe under concurrency by construction, since Postgres serializes the row-level upsert; two simultaneous purchases for the same user both land correctly with no read-modify-write window.
   - **Credit spend at generation time.** `decrement_lesson_credit(user_id)` is a single conditional `UPDATE lesson_access SET lesson_credits = lesson_credits - 1 WHERE user_id = $1 AND lesson_credits > 0 RETURNING lesson_credits`, called from `generate_chapter_lesson` — this is the exact TOCTOU shape already registered as **D45** (`docs/DEFECT-REGISTER.md`: the `(chapter_id, tier)` idempotency pre-check is "a read followed by a write with no lock between them"), and this story does not repeat it: there is no Python-side `SELECT credits, then IF credits > 0: UPDATE`. Two concurrent generation requests from the same user racing the same credit either both see the conditional UPDATE fail (0 rows affected → 402) or exactly one succeeds — never both succeeding on the same credit. D45 itself (the `(chapter_id, tier)` duplicate-lesson race) is untouched by this story and remains open under its own accepted-and-bounded disposition.

## Tasks / Subtasks

- [x] **Task 1 — Wire Stripe config + provider abstraction (AC: #10)**
  - [x] 1.1 Added `stripe_secret_key: str`, `stripe_webhook_secret: str`, `stripe_price_id_lesson_credit: str`, and `stripe_lesson_credits_per_purchase: int = 1` fields to `Settings` in `apps/api/app/config.py`. Added stub values to `tests/conftest.py`'s `_STUB_ENV_VARS` (required fields — the whole suite would otherwise fail `Settings()` construction).
  - [x] 1.2 `apps/api/app/providers/payments/base.py` — abstract `PaymentProvider` with `create_checkout_session(...)` / `verify_and_parse_webhook(...)`, plus `CheckoutSession`/`WebhookEvent` dataclasses so callers never depend on the SDK's own object shape beyond this boundary.
  - [x] 1.3 `apps/api/app/providers/payments/stripe.py` — the only file allowed to `import stripe`. **Found during implementation:** `StripeObject` is deliberately not `dict()`-convertible/iterable (raises `TypeError`) — `.to_dict()` is the real conversion, confirmed empirically against the installed SDK before writing the code, not assumed.
  - [x] 1.4 Added `stripe>=10.0.0` (resolved to 15.5.1) to `pyproject.toml`; `uv lock` re-run.

- [x] **Task 2 — DB migration: `lesson_access`, `stripe_events`, atomic RPCs (AC: #4, #5, #7)**
  - [x] 2.1 `supabase/migrations/20260825000000_stripe_payments_lesson_access.sql`.
  - [x] 2.2 `lesson_access` exactly as specified, reusing `public.set_updated_at()`.
  - [x] 2.3 `stripe_events` exactly as specified.
  - [x] 2.4 RLS on `lesson_access`: one `SELECT`-own policy, no write policy.
  - [x] 2.5 RLS on `stripe_events`: enabled, zero policies.
  - [x] 2.6 `grant_lesson_credits` — atomic upsert, exact grant/revoke shape as `increment_learner_dna_session_count`.
  - [x] 2.7 `decrement_lesson_credit` — atomic conditional UPDATE, returns `FOUND`.
  - [x] **2.8 (added during implementation, not in the original task list):** a THIRD RPC, `record_stripe_event_if_new(p_event_id, p_session_id, p_event_type) RETURNS boolean` — `INSERT ... ON CONFLICT (stripe_event_id) DO NOTHING; RETURN FOUND;`. AC5 requires the idempotency check to be "a durable UNIQUE/primary-key constraint... not an in-process cache **or a SELECT-then-INSERT check**" — a plain PostgREST `.upsert()` call through the Supabase Python client does not reliably expose "did THIS call's insert affect a row" (upsert response shape varies with `Prefer` headers/resolution mode), so a small dedicated RPC mirroring 2.6/2.7's exact pattern was the more correct, less ambiguous implementation of the same principle those two already establish.

- [x] **Task 3 — `apps/api/app/modules/payments/` module (AC: #1, #2, #3, #6, #10)**
  - [x] 3.1 `schemas.py` — `CreateCheckoutSessionResponse`.
  - [x] 3.2 `router.py` — `router = APIRouter(tags=["payments"])`.
  - [x] 3.3 `POST /create-checkout-session` — `CurrentUser`, `@limiter.limit("5/minute", key_func=_get_user_key)`. **Found during implementation:** slowapi's `headers_enabled=True` (set on the shared `limiter`) requires the decorated handler to also declare a literally-named `response: Response` parameter (`_inject_headers` raises otherwise) — the same requirement `generate_chapter_lesson` already has; added and documented in the handler's own docstring.
  - [x] 3.4 `POST /webhook` — raw body read before parsing, no `CurrentUser`, `SignatureVerificationError` → 400 with no DB write.
  - [x] 3.5 Verified-event handling extracted into `apps/api/app/modules/payments/service.py::process_webhook_event` (module NOT in the original file list — see Dev Notes below for why a service layer was added) — idempotency insert first, branch on event type, missing `metadata.user_id` logged ERROR + 200 no-op.
  - [x] 3.6 Registered in `apps/api/app/main.py` at `/api/payments`.

- [x] **Task 4 — Gate lesson generation on `lesson_credits` (AC: #8, #9, #11)**
  - [x] 4.1 Credit check (Gate 8) added after Gate 7 (concurrency), before the `lessons`/`lesson_jobs` insert + ARQ enqueue.
  - [x] 4.2 `decrement_lesson_credit` → `False` raises `HTTPException(402, ...)`; nothing written before this point.
  - [x] 4.3 Regression tests added proving ordering: `test_zero_credits_is_checked_after_the_concurrency_gate_not_before` (429 wins, credit RPC never called) and `test_idempotent_replay_path_does_not_spend_a_second_credit` (Gate 5's 200-replay never reaches the credit gate at all).
  - [x] 4.4 `grant_lesson_credits(user_id, 1)` refund call added to the existing except-block rollback, same best-effort/logged-not-swallowed pattern as the pre-existing `lessons`/`lesson_jobs` deletes.

- [x] **Task 5 — Tests (AC: all)**
  - [x] 5.1 `apps/api/tests/unit/test_payments_router.py` — 9 tests: happy path (asserts the real kwargs Stripe was called with, not just the response), 401, rate-limit-keyed-by-user (source-scan assertion), webhook valid signature grants credit, invalid signature 400 + zero RPC calls, a real `stripe.SignatureVerificationError` premise-assertion test (binding rule 3), idempotency (same event id twice → 1 grant), unsupported event type → 200 no-op + still recorded in the ledger, missing `metadata.user_id` → logged ERROR + 200.
  - [x] 5.2 `test_generate_lesson_endpoint.py` extended: 5 new tests (zero credits → 402 + no state created; gate ordering vs. concurrency; sufficient credits decrements exactly once; idempotent-replay path spends nothing; downstream enqueue failure refunds). Required adding `.rpc()` support to the file's `_FakeSupabase` (it previously had none) and a `credit_available: bool = True` `_Scenario` field, defaulting to True so all 86 pre-existing tests are unaffected. **Found and fixed during implementation:** the first version of the fake's `.rpc()` returned a bare object whose `.execute()` auto-generated a fresh child `MagicMock` instead of the precomputed response — `bool(resp.data)` was therefore always `True` regardless of scenario, silently defeating the 402 test. Fixed with a small `_RpcCall` wrapper whose `.execute()` returns the actual precomputed response; the reused pattern is now also in `test_payments_router.py`.
  - [x] 5.3 `# MOCK-CONTRACT:` marker added at the top of `test_payments_router.py`, naming `test_migration_payments_schema.py` as the real-dependency-adjacent coverage. **Caveat, stated plainly:** that file parses the migration SQL as text — it is not an execution test against a live Postgres instance (none is available in this sandbox), so it verifies the RPC bodies are SHAPED correctly (single UPDATE, no SELECT-then-write, etc.) but does not execute them. This is a real, named limitation, not silently glossed over.
  - [x] 5.4 `test_unbounded_queries.py` re-run against the new/modified files: 11/11 passed, no new finding, no `# BOUNDED:` escape hatch needed.
  - [x] 5.5 `apps/api/tests/test_migration_payments_schema.py` — 14 tests (table existence/columns/constraints for both tables, RLS enabled on both, `lesson_access`'s exactly-one-SELECT-policy/no-write-policy, all three RPCs' grant/revoke shape, and each RPC body's actual SQL shape — e.g. `decrement_lesson_credit` asserted to contain no `SELECT` before its `UPDATE`).

## Dev Notes

- **Provider abstraction.** CLAUDE.md's principle 5 ("Provider abstraction everywhere — no direct provider client calls in business logic") is applied here the same way it is for TTS/Image/Avatar (`apps/api/app/providers/{tts,image,avatar}/`), even though Stripe has no fallback-chain requirement in the PRD the way TTS (Sarvam → Azure → Browser) or Image (GPT Image → Imagen → text-only) do. The reason to still wrap it: testability (mock `PaymentProvider`, not the `stripe` SDK, in every router test) and a single choke point if a second payment provider is ever added. See `apps/api/app/providers/base.py` for the existing abstract-class shape to mirror.
- **Reused patterns, not new ones.** The atomic-RPC pattern (Task 2.6/2.7) is a direct copy of `increment_learner_dna_session_count` in `supabase/migrations/20260813000001_dna_session_count_atomic_increment.sql` — a Python read-modify-write on a shared counter was exactly the bug (D74) that RPC was written to close. The per-user rate-limit key (Task 3.3) is a direct reuse of `apps/api/app/core/rate_limit.py::_get_user_key`, already hardened against D52 (IP-bucket-sharing from a swallowed `InvalidAudienceError`) and D64 (a second, independently-drifted JWKS decoder) — writing a third, payments-specific decoder from scratch would risk reintroducing the same class of bug a third time.
- **Testing standards.** This repo's binding rule 2 ("no test may assert only on a mock it constructed") applies directly to the webhook tests: a test that mocks `grant_lesson_credits` and then asserts the mock was called is a conversation with a mock, not proof credits were granted, unless paired with either a real-Postgres integration test or an explicit `# MOCK-CONTRACT:` marker naming that test (Task 5.3). Binding rule 3 ("any `except SomeLib.Error` needs an executable premise assertion") applies to the webhook signature-verification error path — assert `stripe.error.SignatureVerificationError` really is the exception type raised, the same discipline as `test_openai_exceptions_are_not_httpx_derived`.
- **What this story does NOT touch.** Dev 2's `/payment/success` and `/payment/cancel` pages, the onboarding-flow redirect into Checkout, and any pricing-page UI are explicitly out of scope (cross-team dependency, see below). D45 (the `(chapter_id, tier)` idempotency race in `generate_chapter_lesson`) is pre-existing, accepted-and-bounded, and untouched by this story beyond the new credit-decrement call being inserted after it — this story does not attempt to fix D45.
- **Cross-team dependency (not in scope here).** `docs/master-tracker.md`'s Sprint 4 Dev 2 section lists "Stripe Checkout redirect integrated into onboarding flow" as Dev 2's own Sprint 4 task — it depends on `POST /api/payments/create-checkout-session` (this story) existing and returning a real `checkout_url`, but the frontend redirect/onboarding wiring itself is Dev 2's work, not this story's.

### Project Structure Notes

- **Epic-5's `backend/routers/payments.py` path does not exist in this repo and is corrected here.** This repo's real convention (verified against `apps/api/app/main.py:31-38,210-217` and every existing module under `apps/api/app/modules/`) is `apps/api/app/modules/{module}/router.py`, mounted with `app.include_router(<module>_router, prefix="/api/{module}")`. The new module is therefore `apps/api/app/modules/payments/router.py`, mounted at `/api/payments` — giving the same public route shape epic-5 specifies (`/api/payments/create-checkout-session`, `/api/payments/webhook`) via the correct file layout.
- **The credit-gated endpoint is not `POST /api/content/lessons`, and gating it there would be wrong.** Epic-5's own Payments section says the "upload endpoint" should check `lesson_credits`, and the task brief that generated this story named `POST /api/content/lessons` as the real candidate — but reading the actual code shows the "book-scale" restructuring (Phase 3, see that endpoint's own docstring at `apps/api/app/modules/content/router.py:706-722`) decoupled book upload from lesson generation: `POST /api/content/lessons` (`upload_lesson`) now only stores a PDF and enqueues **chapter detection** — free, no LLM spend, no `lessons` row created at all. The actual LLM-spending, pipeline-enqueuing action is `generate_chapter_lesson`, mounted at `GENERATE_LESSON_PATH = "/books/{book_id}/chapters/{chapter_id}/lessons"` (full path `POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons`, `router.py:1050-1145+`). Gating credits on the upload endpoint would block free PDF ingestion for no reason and would not gate the thing that actually costs money. This story gates the generation endpoint instead — the epic doc and any future citation of this flow should be corrected to match.
- **The epic's `is_admin` / `profiles` table premise (unrelated to this story, noted for the record) does not match the real repo either** — `apps/api/app/modules/admin/router.py`'s own docstring states the admin gate is a static `ADMIN_EMAILS` allowlist checked against the JWT `email` claim, not a `profiles.is_admin` column; no `profiles` table exists in any migration. Out of scope for S4-3, mentioned only because it is the same "epic doc is aspirational, verify against real code" pattern this story corrects for payments.
- **New files this story adds** (none exist yet — confirmed via repo-wide search: zero `stripe` references under `apps/api` or `apps/web`, zero `lesson_access`/`stripe_events` in any of the fourteen files under `supabase/migrations/`):
  - `apps/api/app/modules/payments/__init__.py`, `router.py`, `schemas.py`
  - `apps/api/app/providers/payments/__init__.py`, `base.py`, `stripe.py`
  - `supabase/migrations/20260825000000_stripe_payments_lesson_access.sql`
  - `apps/api/tests/unit/test_payments_router.py`
- **Modified files:** `apps/api/app/config.py` (new Settings fields), `apps/api/app/main.py` (new router include), `apps/api/app/modules/content/router.py` (credit gate in `generate_chapter_lesson`), `apps/api/tests/unit/test_generate_lesson_endpoint.py` (new assertions).

### References

- [Source: CLAUDE.md — Locked Technology Stack table, Development Rules ("No direct provider calls in business logic"), Defect Register binding rules 1-7, BMAD Pre-Implementation Checklist, Sprint Task Branch Rule]
- [Source: docs/SCALE-CONTRACT.md — the six questions and their enforcement table]
- [Source: docs/DEFECT-REGISTER.md#D45 — `(chapter_id, tier)` TOCTOU idempotency race, the shape this story's credit-decrement RPC must not repeat]
- [Source: docs/DEFECT-REGISTER.md#D49 — `RATE_LIMIT_STORAGE_URL` defaulting to `memory://`, the per-replica scope trap this story's idempotency ledger deliberately avoids by being Postgres-durable]
- [Source: docs/DEFECT-REGISTER.md#D52, #D64 — IP-bucket-sharing rate-limit bugs, why `_get_user_key` is reused rather than reimplemented]
- [Source: docs/DEFECT-REGISTER.md#D59 — unbounded-query defect class, the pattern this story's single-row lookups are checked against]
- [Source: docs/bmad/epics/epic-5-platform-core.md — "Payments" section (flow, `lesson_access` shape, key constraints), "Definition of Done" (webhook signature + idempotency test requirements), "Technical Scope" table (payments router path — corrected in Project Structure Notes)]
- [Source: docs/dev1-tracker.md#Sprint-4 — S4-3 task line, S4-4 (rate limiting, partial), S4-5 (RLS audit), S4-7 (runbook, must cover "Stripe webhook failing")]
- [Source: docs/master-tracker.md#Sprint-4 — Dev 2's "Stripe Checkout redirect integrated into onboarding flow" cross-team dependency]
- [Source: apps/api/app/modules/admin/router.py — real module/router pattern and admin-gate convention to mirror/contrast]
- [Source: apps/api/app/main.py:31-38,210-217 — real router-mounting convention]
- [Source: apps/api/app/modules/content/router.py:66,686-851,1050-1290 — `GENERATE_LESSON_PATH`, `upload_lesson` (book ingestion, not a spend point), `generate_chapter_lesson` (the real spend/gate point) with its existing idempotency and rollback branches]
- [Source: apps/api/app/core/rate_limit.py — `_get_user_key`, the per-user rate-limit pattern to reuse]
- [Source: apps/api/app/core/db.py — `get_supabase()` is the service-role client used for all server-side writes]
- [Source: apps/api/app/providers/base.py — abstract provider-class pattern to mirror for `providers/payments/`]
- [Source: supabase/migrations/20260813000001_dna_session_count_atomic_increment.sql — atomic RPC pattern (grant/revoke, `security invoker`, `set search_path = ''`) to copy]
- [Source: supabase/migrations/20260702000000_dpdp_user_consents.sql — RLS/insert-only-audit-table style precedent]
- [Source: .env.example:51-54 — Stripe keys already templated, not yet wired into `Settings`]
- [Source: apps/api/tests/test_env_example_consistency.py:91-97 — confirms an env-example key with no matching `Settings` field is silently skipped, not failed, today]
- [Source: apps/api/tests/unit/test_unbounded_queries.py — the CI guard's scope and mechanism]

## Sprint 4 Sequencing

- **Branch:** `sprint4/s4-3-stripe-checkout`
- **Depends on:** None. This story is fully greenfield and needs only infrastructure already in place from Sprint 0-3 (Supabase project, `CurrentUser`/JWT verification in `dependencies.py`, the per-user rate-limit key in `core/rate_limit.py`). It does not need S4-1 (load test) or S4-2 (pipeline reliability fixes) to land first — payments is orthogonal to the content pipeline's reliability work. It does not need S4-4 (per-route rate limiting) to finish either — the per-user limiter infrastructure it needs already exists and is already in use by `generate_chapter_lesson`; this story reuses it directly rather than waiting on S4-4's own rollout to every other route.
- **Blocks:** 5-5 (S4-5, RLS security audit) — the audit checklist (`docs/security/rls-audit.md`) must include the two new tables this story creates (`lesson_access`, `stripe_events`), so the audit should not be considered complete until this story's migration has landed. 5-7 (S4-7, on-call runbook) — epic-5's own Definition of Done requires the runbook to cover "Stripe webhook failing" as one of its scenarios; that scenario cannot be written accurately (retry semantics, idempotency ledger, refund-on-failure behavior) until this story's webhook design exists.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5), 2026-08-25.

### Debug Log References

- Empirically verified `StripeObject` is not `dict()`-convertible/iterable before writing
  `stripe.py` — `TypeError: StripeObject is not iterable or a mapping; call .to_dict() for a
  plain dict` — confirmed against the installed `stripe==15.5.1` SDK directly.
- Empirically verified `event["data"]["object"]` and `event["id"]`/`event["type"]` subscripting
  work on a real `StripeObject` (constructed via `StripeObject.construct_from`) before relying on
  it in `verify_and_parse_webhook`.
- Full unit suite before and after: 1247 passed / 6 skipped / 3 pre-existing unrelated failures
  (D134, `test_extract_page_bounds.py`, pypdfium2 API mismatch) — identical failure set, zero
  regressions.
- `test_generate_lesson_endpoint.py`'s `_FakeSupabase.rpc()` bug (returning an unconfigured child
  MagicMock from `.execute()` instead of the precomputed response) was caught by its own new test
  failing with the WRONG status code (202 instead of 402) rather than an exception — traced with a
  standalone repro script before fixing, not assumed.
- Ruff and mypy clean on every touched/new file (mypy's one reported error, `providers/llm/
  openai.py:69`, is pre-existing and unrelated — confirmed by scope, not touched by this story).

### Completion Notes List

- AC1-AC11 all implemented and tested. Task 2 added a third RPC beyond the two named in the
  original task list (`record_stripe_event_if_new`) — a more correct, less ambiguous
  implementation of AC5's own "durable constraint, not a SELECT-then-INSERT check" requirement
  than relying on PostgREST upsert-response-shape nuances through the Supabase Python client.
- A `payments/service.py` module was added, not present in the story's original file list —
  houses the three RPC wrappers shared between `payments/router.py`'s webhook handler and
  `content/router.py`'s credit gate, which is the actual mechanism satisfying CLAUDE.md's "modules
  communicate only through service layer, never via direct DB access into another module's
  tables" rule (`content/router.py` never touches `lesson_access`/`stripe_events` directly).
- Not independently verified against a real Supabase/Postgres instance — no live test project
  available in this sandbox. `test_migration_payments_schema.py` verifies the migration SQL's
  shape (tables, RLS, RPC grant/revoke, RPC body structure) by parsing the file as text, matching
  this repo's existing `test_migration_analytics_schema.py`/`test_migration_assessment_schema.py`
  convention — this is real coverage of the SQL as written, but is not the same as executing it.
  Named explicitly in the `# MOCK-CONTRACT:` marker rather than implied to be equivalent.
- Cross-team dependency confirmed still out of scope and untouched: Dev 2's `/payment/success`
  and `/payment/cancel` pages, the pricing page, and the onboarding-flow Checkout redirect.
- D45 (the pre-existing `(chapter_id, tier)` idempotency TOCTOU race) is untouched — the new
  credit gate runs strictly after Gate 5's existing idempotent-replay branch, so it does not
  interact with that defect's accepted-and-bounded disposition.
- No PR opened in this session; branch `sprint4/s4-3-stripe-checkout` has the story-only commit
  followed by this implementation. Not yet run through the 6-agent `/bmad-code-review` gate
  CLAUDE.md requires before merge, and not yet pushed to remote.

### File List

- `apps/api/app/config.py` — 4 new Stripe Settings fields
- `apps/api/app/main.py` — imports + mounts `payments_router` at `/api/payments`
- `apps/api/app/providers/payments/__init__.py` — new, empty
- `apps/api/app/providers/payments/base.py` — new, `PaymentProvider` ABC + `CheckoutSession`/`WebhookEvent`
- `apps/api/app/providers/payments/stripe.py` — new, `StripePaymentProvider` (the only file importing `stripe`)
- `apps/api/app/modules/payments/__init__.py` — new, empty
- `apps/api/app/modules/payments/schemas.py` — new, `CreateCheckoutSessionResponse`
- `apps/api/app/modules/payments/service.py` — new (not in original file list) — RPC wrappers + webhook event processing
- `apps/api/app/modules/payments/router.py` — new, the two endpoints
- `apps/api/app/modules/content/router.py` — Gate 8 (credit check) + refund-on-failure added to `generate_chapter_lesson`
- `supabase/migrations/20260825000000_stripe_payments_lesson_access.sql` — new — `lesson_access`, `stripe_events`, 3 RPC functions
- `apps/api/tests/unit/test_payments_router.py` — new, 9 tests
- `apps/api/tests/unit/test_generate_lesson_endpoint.py` — 5 new tests + `_FakeSupabase.rpc()`/`_RpcCall`/`credit_available` support added
- `apps/api/tests/test_migration_payments_schema.py` — new, 14 tests
- `apps/api/tests/conftest.py` — 3 new stub env vars (Stripe Settings fields are required)
- `apps/api/pyproject.toml` / `apps/api/uv.lock` — `stripe>=10.0.0` added
