# Sprint 4 Plan & Tracker — Load Test + Calibration + Stripe + Hardening

**Owner:** Dev 1 (developer1-cybersmith)
**Sprint window:** Weeks 8–9 (per `docs/dev1-tracker.md`, due ~2026-08-13; today is 2026-08-25 — **sprint is already past its original due date, 0/8 done**)
**Source tasks:** `docs/dev1-tracker.md` §Sprint 4 (S4-1…S4-8), cross-referenced against `docs/master-tracker.md` and `docs/bmad/epics/epic-5-platform-core.md` (Epic E-05, Platform Core)
**Process:** BMAD story-first (`CLAUDE.md` → BMAD Pre-Implementation Checklist + Sprint Task Branch Rule + 6-Agent Code Review Gate)
**Last updated:** 2026-08-25 — this document created; all 8 story files drafted, none started

---

## 0. How to use this document

This is the **single tracker for the whole sprint** — update it in place as work proceeds, the same way `docs/dev1-tracker.md` tracks Dev 1's other sprints. Do not create a second competing tracker.

**Status values** (borrowed from the `bmad-sprint-planning` skill's state machine, applied per-story):

`backlog` → `ready-for-dev` → `in-progress` → `review` → `done`

All 8 stories are currently **`ready-for-dev`** — the story file exists with full ACs and a completed Scale & Load section, but no branch, no commit, no code.

**Whenever a story's status changes:**
1. Update its row in the [Master Tracker Table](#2-master-tracker-table) below.
2. Update the story file's own `Status:` line (top of `docs/stories/5-N-*.md`) to match.
3. Update the **Quick Status Dashboard** counts in §1.
4. Update **Last updated** in this header.

Do this in the same response/commit that changes the story's status — mirrors the auto-update discipline `CLAUDE.md` already requires for `docs/dev1-tracker.md`.

**Per-story detail lives in the story file, not here.** This document is the sprint-level map (sequencing, dependencies, cross-cutting risk); each `docs/stories/5-N-*.md` is the full spec (Acceptance Criteria, Scale & Load, Tasks/Subtasks, Dev Agent Record).

### ⚠️ Process gap to close before implementation starts

All 8 story files were drafted in one batch, directly on the current working branch (`sprint3/real-world-pdf-eval-coverage`), **not** yet following `CLAUDE.md`'s **Sprint Task Branch Rule** (`git checkout main && git checkout -b sprint4/s4-N-slug` as the first action, story file as the sole first commit, pushed, before any implementation). Before starting work on story 5-N:

1. `git checkout main && git checkout -b sprint4/s4-N-slug` (branch names are already assigned — see the table below)
2. Move/copy that one story file onto the new branch as the **only** file in the first commit: `git commit -m "docs(story-first): Story 5-N — {title}"`
3. Push the story-only commit, verify it's chronologically first on the branch
4. Only then begin the RED phase (failing tests first)

This has not been done yet for any of the 8 — do it per-story, right before picking that story up, not all at once (creating all 8 branches now, before any of them is actively being worked, would just recreate the same batching problem one level down).

**5-4 done this way, 2026-08-25** — branch `sprint4/s4-4-rate-limit-per-route` created from `main`, story file committed alone first, implementation (RED→GREEN, mutation-checked) committed second. Confirmed `main`'s `docs/dev1-tracker.md` (7 Sprint-4 tasks) differs from the copy that was on `sprint3/real-world-pdf-eval-coverage` (8 tasks, includes S4-8/D121) — that branch's S4-8 addition hasn't merged to `main` yet. Not a blocker for 5-4; worth resolving before 5-8's own branch is cut from `main`.

---

## 1. Quick Status Dashboard

| Story | Task | Status | Depends on | Blocks |
|---|---|---|---|---|
| 5-1 | Load test: 50 concurrent lesson generations | `ready-for-dev` | — (soft: after 5-4) | 5-2 |
| 5-2 | Pipeline reliability fixes from test sessions | `ready-for-dev` | 5-1 (hard) | 5-7 |
| 5-3 | Stripe Checkout integration | `done` — 8-layer code review complete, 19 patches applied incl. a real money-losing bug (D136, closed) and an architecture-rule violation (`import stripe` in router.py); D137 registered/deferred by user decision; Dev 2's frontend pages still open (cross-team) | — | 5-5 (partial), 5-7 |
| 5-4 | Rate limiting — per-route limits | `done` — D49 fixed + guarded, 15 tests, mutation-checked both directions; 6-layer `/bmad-code-review` complete, all findings resolved; not yet pushed/merged | — | 5-1 (soft) |
| 5-5 | RLS security audit on all Supabase tables | `ready-for-dev` | 5-3 (partial) | Epic-5 DoD → W10-1 |
| 5-6 | Railway/Fly backups + disaster recovery tested | `ready-for-dev` | — | 5-7 |
| 5-7 | On-call runbook (5 failure scenarios) | `ready-for-dev` | 5-1, 5-2, 5-3, 5-6 | W10-3 |
| 5-8 | Resolve dead Imagen 4 Fast fallback (D121) | `ready-for-dev` | — | 5-8b (new, TBD) |

**Totals:** 8 stories · 2 done · 0 in-progress · 0 review · 6 ready-for-dev

---

## 2. Master Tracker Table

| ID | Title | Branch | Story File |
|---|---|---|---|
| S4-1 / **5-1** | Load test: 50 concurrent lesson generations | `sprint4/s4-1-load-test-concurrent` | [`5-1-load-test-50-concurrent.md`](stories/5-1-load-test-50-concurrent.md) |
| S4-2 / **5-2** | Pipeline reliability fixes from test sessions | `sprint4/s4-2-reliability-fixes` | [`5-2-pipeline-reliability-fixes.md`](stories/5-2-pipeline-reliability-fixes.md) |
| S4-3 / **5-3** | Stripe Checkout integration (hosted page) | `sprint4/s4-3-stripe-checkout` | [`5-3-stripe-checkout-integration.md`](stories/5-3-stripe-checkout-integration.md) |
| S4-4 / **5-4** | Rate limiting — per-route limits | `sprint4/s4-4-rate-limit-per-route` | [`5-4-rate-limiting-per-route.md`](stories/5-4-rate-limiting-per-route.md) |
| S4-5 / **5-5** | RLS security audit on all Supabase tables | `sprint4/s4-5-rls-audit` | [`5-5-rls-security-audit.md`](stories/5-5-rls-security-audit.md) |
| S4-6 / **5-6** | Backups confirmed + disaster recovery tested | `sprint4/s4-6-backups-dr` | [`5-6-railway-backups-dr-test.md`](stories/5-6-railway-backups-dr-test.md) |
| S4-7 / **5-7** | On-call runbook (5 failure scenarios) | `sprint4/s4-7-oncall-runbook` | [`5-7-oncall-runbook.md`](stories/5-7-oncall-runbook.md) |
| S4-8 / **5-8** | Resolve dead Imagen 4 Fast fallback (D121) | `sprint4/s4-8-imagen-fallback` | [`5-8-imagen-fallback-migration.md`](stories/5-8-imagen-fallback-migration.md) |

---

## 3. Execution sequencing (recommended waves)

Built from each story's own **Sprint 4 Sequencing** section (real logical dependencies each story author derived from the code, not an assumed order). Stories in the same wave have no dependency on each other and can run fully in parallel across however many people/agents are available.

```
Wave 1 (start now, parallel)     Wave 2                Wave 3            Wave 4 (last)
──────────────────────────────  ─────────────────────  ────────────────  ─────────────────
5-4  Rate limiting  ──soft──►   5-1  Load test  ──────► 5-2  Reliability
                                                          fixes  ────────► 5-7  Runbook
5-3  Stripe Checkout ─────────────────────────────────────────────────────────► (needs 5-1,
  │                                                                              5-2, 5-3, 5-6)
  └──partial──► 5-5  RLS audit (15 existing tables now;
                       lesson_access/stripe_events after 5-3)

5-6  Backups + DR ──────────────────────────────────────────────────────► 5-7

5-8  Imagen decision (fully standalone — run any time, due end of Week 10)
       └──► spawns 5-8b (new implementation story, not yet created)
```

**Wave 1 — start immediately, no blockers:** 5-4 (lightest story in the sprint — AC1/AC2 already merged, only the Redis-backed limiter storage + startup guard remain), 5-3 (longest lead time — fully greenfield payments module, start early), 5-6 (mostly ops/docs, has an external billing prerequisite to resolve early — see §5), 5-8 (a decision, not engineering effort — calendar time to get sign-off matters more than developer-hours), 5-5 (the 15 pre-existing tables can be fully audited now, independent of 5-3).

**Wave 2:** 5-1 — technically has no hard dependency, but should follow 5-4 so the load test measures the *intended* per-deployment rate limit rather than the current per-process-multiplied one (D49).

**Wave 3:** 5-2 — hard-blocked on 5-1's real output; its Tasks 1–2 (triage) cannot be written until 5-1 actually runs.

**Wave 4:** 5-7 — hard-blocked on 5-1, 5-2, 5-3, and 5-6 all landing; write this runbook from what actually happened this sprint, not from first principles. 5-5's `lesson_access`/`stripe_events` audit rows also close out once 5-3 lands.

---

## 4. Per-story findings (from grounded research, not the tracker's one-liners)

> Full detail, ACs, and Scale & Load answers are in each story file. This is the "what a reviewer should already know before opening it" summary.

**5-1 — Load test.** There are **two** distinct endpoints the tracker's "50 concurrent lesson generations" could mean — `POST /api/content/lessons` (book ingestion, 5/min limit) vs. the real Phase-B generation route `POST /api/content/books/{id}/chapters/{id}/lessons` (3/min;20/hour limit) — the story reconciles both rather than picking one silently. `max_concurrent_generations_per_user=3` means 50 concurrent generations requires ≥17 distinct test users, not 50 requests from one account. No load-test tooling (locust/k6) exists anywhere in the repo yet — this is genuinely greenfield. Directly closes **D129** (`DEFECT-REGISTER.md`: "no multiple-concurrent-real-user load has ever been run against this pipeline").

**5-2 — Reliability fixes.** Deliberately written as a *triage protocol*, not a fixed task list, since its real scope doesn't exist until 5-1 runs. Every failure 5-1 surfaces must get a `D-nn` register entry before being fixed (binding rule 5), and every fix ships with a regression guard (binding rule 7). The four mandatory categories (retry exhaustion, cost-ceiling mid-flight, Redis drops, node timeout) are checked even if the load test doesn't organically trigger all four.

**5-3 — Stripe.** 100% greenfield — zero Stripe references anywhere in the repo, no `lesson_access`/`stripe_events` tables in any of the 14 existing migrations. Epic-5's `backend/routers/payments.py` path is stale — real convention is `apps/api/app/modules/payments/router.py`. **Open product decision, not yet made:** actual price / credits-per-purchase (epic-5 only says "single tier, per-lesson credit model," no number). Frontend redirect wiring is Dev 2's separate Sprint 4 task, not in scope here.

**5-4 — Rate limiting.** The tracker's "not yet configured" claim is **stale** — per-route decorators already exist on both real endpoints in `main`. What's actually still open: **D49** (`RATE_LIMIT_STORAGE_URL` still defaults to `memory://`, so the ceiling multiplies by replica count — confirmed by direct code read) and **D52**-adjacent per-user-not-IP keying to verify. Lightest story in the sprint.

**5-5 — RLS audit.** Found a real, currently-unresolved contradiction: the `user_consents.consent_type` CHECK constraint doesn't include `'data_processing'`, which Epic-5's own Definition of Done requires being written at signup — as written today, that DoD line **cannot** be satisfied without a new migration. Also: `attention_events` DELETE/UPDATE policies lack the dual consent-check that INSERT has. The existing Postgres RLS test only runs against a local shim (`apps/api/tests/integration/supabase_shim.sql`), never the real Supabase project — flagged as insufficient for a real audit sign-off.

**5-6 — Backups/DR.** **Blocked on an external, unconfirmed billing action:** Epic-5's own Dependencies table says Supabase must be upgraded to the Pro plan before this can even start, and nothing in the repo confirms that happened. Also: Redis's current physical location is now **confirmed, not just unconfirmed** — see the Railway→Fly finding below, resolved directly against `.env.example` after this story was drafted.

**5-7 — Runbook.** Deliberately sequenced last. The tracker's 5 scenarios and Epic-5's 4 scenarios don't fully match (Epic-5 adds "Stripe webhook failing," missing from the tracker's list) — the story requires an explicit reconciliation decision once 5-3 exists, not a silent pick. Flags that no monitoring/alerting exists yet (W10-2 isn't done), so no resolution step should imply "you'll get paged."

**5-8 — Imagen fallback (D121).** Best-specified task in the sprint already. Story correctly separates **deciding** (this story, gates on team sign-off, due before Week 10 ends) from **implementing** (a new story to be created once the decision lands — do not conflate the two). Flags a real, previously-unregistered concurrency gap in `check_ceiling`/`accumulate_cost` found during research — out of this story's scope, needs its own disposition.

---

## 5. Cross-cutting risks (surfaced across multiple stories — read once, applies everywhere)

| Risk | Found in | Why it matters |
|---|---|---|
| ~~`CLAUDE.md`'s Locked Technology Stack table said "Deploy: Railway + GitHub Actions — railway.toml," but Railway compute was retired 2026-08-14~~ — **✅ FIXED 2026-08-25.** `CLAUDE.md`'s Deploy row, the Cache/Queue/PubSub row, and the two Development-Rules/Roadmap prose mentions of the India-region migration are now corrected to say Fly.io (Mumbai), citing `fly.toml` + `docs/decisions/ADR-001-india-region-migration-topology.md`. | 5-1, 5-4, 5-6 | S4-6's task name ("Railway backups") was testing against a possibly-wrong mental model of the infra — now corrected at the source doc. |
| **Redis was required to move to Mumbai in the SAME change as compute (ADR-001 §4, non-negotiable) — confirmed 2026-08-25 that it did NOT.** `.env.example:21` still points `REDIS_URL` at a `railway.app` (US-west) host under a "Railway Redis" comment. Compute now runs in Mumbai (`fly.toml`) while cache/queue/pub-sub remains in the US — the exact residency-defeating shape ADR-001 warned against. Now called out explicitly in `CLAUDE.md`'s Cache/Queue/PubSub row as an OPEN gap, not silently inherited. | 5-6 (its own research only got as far as "unconfirmed" — this is now confirmed and worse than assumed) | Backup/DR story (5-6) can't verify AOF persistence on a service whose *region* is now known to be wrong, not just unconfirmed. This is also a live DPDP/data-residency compliance gap, arguably higher priority than any single Sprint 4 story — worth its own follow-up story, not folded silently into 5-6. |
| `RATE_LIMIT_STORAGE_URL` defaults to `memory://` (**D49**, still open, confirmed by direct read). | 5-1, 5-4 | Any load-test numbers or rate-limit ACs measured before this is fixed reflect a per-process ceiling, not the intended per-deployment one. |
| Global (not per-tenant) circuit breaker (**D129**'s own risk #1). | 5-1, 5-2 | One user's provider failures can trip the breaker for every concurrent user during the load test — by design today, worth observing/reporting rather than treating as a bug to silently fix mid-sprint. |
| `D45` — `(chapter_id, tier)` idempotency check-then-insert race, no UNIQUE constraint. | 5-1, 5-3 | Concurrent duplicate requests both bill; both the load test and Stripe's credit-decrement logic touch this exact hazard shape — each story treats it as an existing, registered, out-of-scope risk rather than silently re-discovering it. |
| Stripe pricing/credits-per-purchase is genuinely undecided at the product level. | 5-3 | Not an engineering blocker (ship as a config constant), but someone needs to make this call before the story can be called done. |
| Supabase Pro-plan upgrade status is unconfirmed in-repo. | 5-6 | External/billing action outside this sprint's code — verify first, don't assume. |

---

## 6. Definition of Done — Sprint 4

Aggregated from `docs/dev1-tracker.md` §Sprint 4 ACs and `docs/bmad/epics/epic-5-platform-core.md`'s Definition of Done (the platform items relevant to Dev 1's slice):

- [ ] 50 concurrent lesson generations complete without crash; results (queue-wait vs. execution duration, worker topology) documented — **5-1**
- [ ] Every failure mode 5-1 surfaces is registered (`D-nn`) and fixed with a regression guard; no silent failures — **5-2**
- [ ] Student can complete a Stripe-hosted checkout; webhook idempotently unlocks `lesson_credits`; signature validation tested valid + invalid — **5-3**
- [ ] `POST .../lessons` returns 429 + `Retry-After` past 5/min, keyed per-user not per-IP; limiter storage is shared (Redis), not per-process memory — **5-4**
- [ ] RLS audit report committed; every table's policy verified; DPDP `consent_type` gap resolved or explicitly registered — **5-5**
- [ ] Backup restore drill executed on a scratch project; <30 min; data integrity confirmed; DR doc committed — **5-6**
- [ ] On-call runbook committed, ≤5 steps per scenario, reviewed by a teammate who didn't write it — **5-7**
- [ ] D121 decision recorded (owner + rationale) in `DEFECT-REGISTER.md` and `CLAUDE.md`; follow-on implementation story created if needed — **5-8**

Sprint 4 is not "done" until every box above is checked **and** each story's own file-level Dev Agent Record is filled in (Agent Model Used, Completion Notes, File List) — not just this table.

---

## 7. Looking ahead — Week 10 gating

Per `docs/dev1-tracker.md` §Week 10, none of W10-1…W10-4 have their own stories yet — they should be storied the same way once Sprint 4 is substantially done. What's already known about the gate:

- **W10-1** (production deployment verified end-to-end) is gated by Epic-5's overall Definition of Done, which **5-5** (RLS audit) is itself is a line item of.
- **W10-2** (monitoring dashboards live) is informed by **5-2**'s reliability findings (what to alert on) but not hard-blocked.
- **W10-3** (on-call rotation established) is directly blocked on **5-7** (can't rotate a team through a runbook that doesn't exist).
- **W10-4** (first paying user job monitored live) requires **5-3** (Stripe) to be live in production.

---

## Change Log

| Date | Change |
|---|---|
| 2026-08-25 | Document created. All 8 Sprint 4 story files drafted (`docs/stories/5-1` … `5-8`) via parallel grounded research. No implementation started. Sprint Task Branch Rule not yet applied to any story (see §0 process gap). |
| 2026-08-25 | `CLAUDE.md` corrected: Deploy row, Cache/Queue/PubSub row, and two Development-Rules/Roadmap prose mentions updated from Railway to Fly.io (Mumbai), per `fly.toml` + ADR-001. New confirmed finding folded in: Redis did **not** move with compute (`.env.example:21` still Railway/US-west) — an open data-residency gap, not just an unconfirmed one. Branch setup for the 8 stories deliberately deferred — current branch still has pending work to push first; branches will be created per-story right before each is picked up, not all at once. |
| 2026-08-25 | **Story 5-4 (S4-4, rate limiting) implemented, code-reviewed, `done`.** Branch `sprint4/s4-4-rate-limit-per-route` cut from `main` (story-only commit first, per §0). AC1/AC2 confirmed pre-existing (tracker's "not yet configured ✗" was stale). D49 fixed: `assert_rate_limit_storage_configured()` added to `core/rate_limit.py`, wired first into `main.py`'s `lifespan()`. Task 2's env-var wiring (pointing `RATE_LIMIT_STORAGE_URL` at a real shared Redis) left explicitly open — blocked on ADR-001 §4's Redis-location decision, out of a code branch's reach. **Also discovered:** `main`'s `docs/dev1-tracker.md` has only 7 Sprint-4 tasks — S4-8 (Imagen/D121) exists only on `sprint3/real-world-pdf-eval-coverage`, not yet merged to `main`. |
| 2026-08-25 | **Story 5-4 8-layer `/bmad-code-review` complete, all findings resolved.** 2 decisions (keep hard-fail; fix the phantom `D129` register citation's wording only), 10 patches applied, 4 deferred, 6 dismissed (2 refuted by independent re-execution). Headline fix: the guard's exact-string `"memory://"` match missed non-canonical variants (empty string, case, whitespace, URI suffix) that all empirically resolved to real `MemoryStorage` — replaced with `limits.storage_from_string` + `isinstance(..., MemoryStorage)`, the same factory `Limiter` itself uses; `limiter` and the guard now share one single-source-of-truth constant instead of two independent env reads. Added a lifespan-wiring guard test, strengthened `Retry-After` int-parseability, added a real-production-key-func cross-instance test, fixed citation errors. Both mutation-check directions now performed. Full suite: 1248 passed (was 1241) / 6 skipped / same 3 pre-existing unrelated failures — zero regressions. Not yet pushed to remote or merged. |
| 2026-08-25 | **Story 5-3 (S4-3, Stripe Checkout) implemented, moved to `review`.** Branch `sprint4/s4-3-stripe-checkout` cut from `main` (story-only commit first). New: `providers/payments/` (Stripe SDK wrapper, the only file importing `stripe`), `modules/payments/` (checkout-session + webhook endpoints, service layer), migration `20260825000000_stripe_payments_lesson_access.sql` (`lesson_access`, `stripe_events`, 3 atomic RPCs — a third RPC, `record_stripe_event_if_new`, added beyond the two originally scoped, for a more reliable AC5 idempotency guarantee than a PostgREST upsert call). `generate_chapter_lesson` gained a credit gate (402 on zero credits, refund on downstream failure) after the existing concurrency gate. 28 new tests across 3 files; caught and fixed a real bug in `test_generate_lesson_endpoint.py`'s own test fake along the way (`.rpc().execute()` was returning an unconfigured mock instead of the precomputed response, making the 402 test pass for the wrong reason until fixed). Full suite 1247 passed / 6 skipped / same 3 pre-existing failures — zero regressions. `docs/dev1-tracker.md` S4-3 flipped. **Cross-team, confirmed out of scope:** Dev 2's `/payment/success`/`/payment/cancel` pages and onboarding redirect. Not yet through `/bmad-code-review`; not pushed. |
| 2026-08-26 | **Story 5-3 8-layer `/bmad-code-review` complete, `done`.** 1 decision (register + defer the residual decrement-outside-try window, D137), 19 patches applied, 6 deferred, 5 dismissed. **Headline fix (D136, closed):** webhook idempotency-marking and credit-granting were two non-transactional RPC calls — a transient failure in the grant call after the idempotency row committed permanently lost the credit on Stripe's retry, a `silent-wrong-result` scale finding found independently by 3 layers. Fixed with one new atomic RPC (`record_stripe_event_and_grant_credits`) doing both steps in a single transaction. **Also fixed:** a confirmed `import stripe` violation in `payments/router.py` (one reviewer wrongly claimed it didn't exist — verified directly); relative `success_url`/`cancel_url` that would have rejected every real Stripe call; a missing `payment_status` check; an unbounded webhook body read (413 cap added); missing error handling on the Stripe API call and on malformed-but-signed payloads; a fabricated "D134" register citation and an under-scoped mypy claim (corrected to the real repo-wide count of 3, matching binding rule 1); moved the migration test into `tests/unit/` so it's actually CI-gated. Full suite verified against CI's *exact* gating command this time: 1292 passed / 6 skipped / same 3 pre-existing failures — zero regressions. Not yet pushed to remote or merged. |
