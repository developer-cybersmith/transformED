# Defect Register & Binding Decisions

**Owner:** Dev 1 · **Created:** 2026-07-29 · **Last updated:** 2026-07-30 · **Status:** ACTIVE

> **AMENDED 2026-07-30.** The line below previously read *"none is waiting on Dev 1"*. A
> route-by-route frontend wiring audit run **after** that claim was made found **three Dev 1
> defects** — D31, D32, D33 — one of which breaks the documented frontend setup path. The
> claim was wrong when written. Full audit:
> **`docs/reports/frontend-wiring-audit-2026-07-30.md`**.
>
> See also `docs/handoffs/DEV1-FINAL-HANDOVER.md` (amended). All open entries carry a named
> owner and a trigger.
>
> ⚠️ **ID COLLISION — this actually happened, twice, on 2026-07-30.**
>
> 1. The wiring-audit tooling emitted labels `D-1…D-30` that collide numerically with register
>    ids meaning something entirely different (audit `D-28` = a `package_builder` subscript bug;
>    register **D28** = the chapter/subsection hierarchy inversion). The report therefore
>    relabels everything **`W-*`**. **`W-…` ids are NOT register ids.**
> 2. **Two devs independently claimed D29 and D30 the same day.** The Sprint 2 completion audit
>    landed D29 (DPDP `user_consents`) / D30 (3 failing tutor tests) on `main` while Dev 1's
>    wiring audit was being written against the same free ids. Dev 1's entries were renumbered
>    **D31–D37** on discovery; nothing was overwritten.
>
> **Rule going forward: re-read the highest allocated id from `main` immediately before writing
> a new entry, and never from a branch.** This register has no id allocator, so concurrent
> branches will keep colliding until it does.

This file exists because `docs/deferred-work.md` did not. That file was created to hold
deferred findings; it contains **zero items** across a period in which the story files
accumulated 131 `[Review][Defer]` markers. A register nobody writes to is worse than no
register, because it lets people believe the deferral was recorded.

## How this file is binding

Every entry names an **enforcement**: a test, a CI gate, or the word **DISCIPLINE**.

`DISCIPLINE` means *nothing stops us breaking this*. That label is not an admission of
laziness — it is the most important column in the table. On 2026-07-29 we established
empirically that prose guidance does not hold: Dev 1 wrote `DEV1-FIX-PLAN.md`, then
deviated from it four times in one day (the "Honest framing" instruction, sub-tasks 5.1,
5.5 and 6.3). The plan was correct each time. It was simply not enforced.

**So the rule is: prefer a failing test to a paragraph.** Any decision that *can* be
machine-checked *must* be, and the count of `DISCIPLINE` rows is the honest measure of how
fragile this register is.

## Closure rule

An entry may move to `CLOSED` only when its **Enforcement** column names something that
runs in CI and would fail if the defect returned. "Fixed" is not closure. A fix without an
enforcement is `FIXED-UNGUARDED`, which is a distinct and worse state than it sounds —
`{**state, ...}` was "fixed" once and reached 18 sites.

---

## Part 1 — Root causes

Ranked by number of defects each explains. Derived from a 10-agent analysis on 2026-07-29;
every claim below was re-verified by execution before being written here.

| # | Root cause | Explains | Evidence |
|---|---|---|---|
| **RC-1** | **Mocks are written by the consumer and never reconciled with the producer.** `CLAUDE.md`'s anti-deadlock rule — *"each dev mocks the other's interface"* — was correct for Week 1 and has **no expiry clause**. It is now the primary bug-concealment mechanism. | 12 of 17 | Bug D9 replanted on a different table today: **776 passed, 0 failed**. 567 of 2,328 assertions (24%) describe a conversation with a mock rather than an outcome. |
| **RC-2** | **Nothing in the process reads both ends of a seam.** `graph.py` is ~4,600 lines; seams are relationships between functions ~2,000 lines apart, and a story diff shows one end. | 9 of 17 | D11 is the pure case: a 6,000-char prompt window and a 90%-coverage guard, each defensible, jointly satisfiable only when `len(raw_text) ≤ 6,667`. |
| **RC-3** | **CI verifies roughly half of what the ACs claim.** | why they survived weeks | `pytest tests/unit tests/integration` skips the root `tests/` dir (22 real failures) and uses `-x`. The web job has **no `pnpm test`** at all. |
| **RC-4** | **Detection works; disposition does not.** Findings are recorded and never closed. "Matches existing accepted pattern" is a ratchet that turns instance #1 of a defect class into standing justification for #2–18. | the *feeling* of recurrence | 131 defer markers → **0 registered items**. That ratchet is literally how `{**state, ...}` reached 18 sites. |
| **RC-5** | **The mandated 5-agent review gate is a 3-agent gate in the skill.** | D12–D17 | `CLAUDE.md` requires Story Quality + Process Integrity; `bmad-code-review/SKILL.md` ships only Blind Hunter, Edge Case Hunter, Acceptance Auditor. Story Quality is chartered for exactly the question that would have killed D12–D17: *"does this AC measure the behaviour, or a proxy for it?"* |

### The finding that reframes everything

**9 of 11 pre-existing defects never worked for a single minute.** Only 1 of 17 is a true
regression. This is not an unstable codebase — it is a codebase whose verification never
confirmed anything worked, so we meet the same never-tested assumption in a new subsystem
and experience it as recurrence.

Median time-to-discovery was **13 days**, which measures *when a human read the code*, not
when anything detected anything.

---

## Part 2 — Defect register

Class key: **BW** born-wrong (never worked) · **REG** regression · **LAT** latent, unlatched
by a later fix · **SELF** self-inflicted while fixing · **EXT** wrong model of an external
system.

### Closed — fixed AND guarded

| ID | Defect | Class | Decision | Enforcement |
|----|--------|-------|----------|-------------|
| D1 | `return {**state, ...}` at 18 sites re-appended six `operator.add` channels → 16× in one clean run; ~4× real TTS spend | REG | Return only the node's own reduced keys. Never spread state into a reducer channel. | `test_node_return_shape.py` — AST scan with taint-tracking; e2e duplication assertions |
| D2 | `_FAN_OUT_STATE_KEYS` omitted `"tier"`; a `Send()` payload *replaces* state, so all six Phase-1 nodes read the T2 default. Every T1/T3 lesson shipped T2 content while marked complete. | BW | Fan-out payload must carry every key any Phase-1 node reads. | `test_fan_out_state_keys.py`; `test_tier_differentiation_and_cost.py` (kills the mutation that drops `"tier"` at source) |
| D3 | **Zero** OpenAI exceptions derive from `httpx.HTTPError`, so `with_retry` never classified any of them. A 429 was fatal. | EXT | Classify SDK exceptions by `status_code`, network class by type. Guard the import. | `test_retry.py::test_openai_*`; `test_openai_exceptions_are_not_httpx_derived` pins the premise |
| D4 | SDK default `max_retries=2` under `with_retry(3)` = 9 HTTP requests/call, two backoff schedules, 600s read timeout | EXT | `max_retries=0`; `core/retry.py` owns retry exclusively. Timeout must be an explicit `httpx.Timeout(..., connect=5.0)` — a bare float overwrites `connect`. | `test_openai_clients_disable_sdk_retries_and_set_explicit_timeouts` |
| D5 | `record_failure` inside the retried function counted attempts, not logical calls → breaker tripped ~3× too fast once D3 was fixed | LAT | Breaker accounting lives in `guard_breaker`, outside the retry decorator. Never in a provider module. | `test_breaker_accounting.py`; `test_tts_providers_no_longer_record_breaker_outcomes_themselves` |
| D6 | `raise ... from None` does **not** clear `__context__`; the httpx exception it holds embeds the key-bearing URL | EXT | Build the sanitized error inside `except`, raise it **after** the block exits. Assigning `__context__ = None` does not work. | `test_sanitized_error_does_not_retain_the_original_via_context` |
| D7 | `_fallback_narration` discarded narration text that was present in state | BW | Recover by `segment_id`; lift `["script"]` only — `Narration` is `extra="forbid"` | `test_package_builder_node.py` AC-1 suite |
| D8 | Imagen's key-redaction converted retryable errors into un-retryable `RuntimeError` | BW | `SanitizedHTTPError` carries `status_code` + `network_error` | `test_imagen_network_error_is_retried` |
| ~~D19~~ | **CLOSED 2026-07-29.** `redis.exceptions` defines its OWN `TimeoutError`/`ConnectionError` shadowing the builtins by NAME without inheriting from them, so `except (..., TimeoutError)` never matched one. `is_circuit_open()` is the first statement of every `@with_retry` body and talks to Redis, so a blip killed the node before the provider was contacted — permanently. | EXT | Three layers: `is_circuit_open` fails **open** (inner-body split so the guard covers the HALF_OPEN promotion *write*, not just reads); redis errors classified transient; `guard_breaker` no longer counts a redis error as a **provider** failure (5 blips/120s would open the breaker for a provider never contacted). | `test_redis_exceptions_are_not_the_builtins` pins the premise; `test_redis_errors_are_retried_then_succeed`; `test_is_circuit_open_fails_open_on_a_write_failure_too`; `test_redis_failure_does_not_open_the_breaker` — **mutation-verified, 9/9 caught** |
| ~~D20~~ | **CLOSED 2026-07-29.** `httpx.RemoteProtocolError` is neither `NetworkError` nor `TimeoutException` (sibling under `TransportError`), so a server closing the connection mid-response was never retried. | EXT | Named **explicitly**, never via its parent: `httpx.ProtocolError` also covers `LocalProtocolError` (*we* built a bad request — cannot succeed on attempt two), and `TransportError` also covers `UnsupportedProtocol`. Widening is the tempting wrong fix. | `test_remote_protocol_error_is_retried_then_succeeds` + `test_client_side_protocol_errors_are_not_retried` — the latter is the only test that fails if someone widens to `ProtocolError`/`TransportError` |
| ~~D23~~ | **CLOSED 2026-07-29 (PR #113).** `lesson_ready` reached no client: the worker published to `lesson_ready:{session_id}` from `lesson_row.get("session_id") or lesson_id`, but `lessons` has **no `session_id` column**, so the fallback always fired — while `core/websocket.py` registered connections under the client-supplied `crypto.randomUUID()`. The keys could never match. The right channel was produced **by accident**, one migration away from silently breaking. | BW | **Dev 4 chose option A** (handoff §2): key by `lesson_id` — generation completion is lesson-scoped, not viewer-scoped. Dev 4 fans out from a `lesson_waiters:{lesson_id}` set. Dev 1 deleted the accidental read and the stale payload comment. No schema change, no §16 gate. | `test_lesson_ready_routing_key.py` — **mutation-verified 4/4**. The load-bearing test feeds a row that DOES carry a `session_id` and asserts the key ignores it; plus a premise test that `lessons` must not gain the column silently. **Note: `test_schema_column_guard.py` does NOT cover this shape** — it walks `.select(...)`, this was a `dict.get()` on a fetched row |
| ~~D27~~ | **CLOSED 2026-07-29 by Dev 2 (commit 158e51f).** `next build` failed on a missing Suspense boundary around `useSearchParams()` at `/signin`, so `apps/web` had **never produced a production build** and was never deployable. Invisible to every workflow anyone used — `next dev` does not prerender and `vitest` does not either — and the one job that would have caught it (D25) had been dead since it was written. | BW | Dev 2 wrapped `<SignInForm />` in `<Suspense fallback={<SignInFormSkeleton />}>`. Dev 1 raised it and deliberately left the fallback choice to Dev 2, since it is visible UX on their page. | The `Build` step in the web job — **verified green in CI run 30470590163**, the first successful web job in the repo's history |
| D25 | **The entire `web` CI job has never executed on any commit.** `cache-dependency-path: apps/web/pnpm-lock.yaml` — but this is a pnpm *workspace*, so the single lockfile is at the repo root. `actions/setup-node` failed with "Some specified paths were not resolved", killing the job before install. Lint, type-check and build have therefore never run. Compounding it, `pnpm type-check` did not exist as a script in `apps/web/package.json` at all, so the step would have failed even once setup-node was fixed. | SELF (infra) | Point at the root lockfile; add `"type-check": "tsc --noEmit"`. Verified 2026-07-29: lint 0 errors, `tsc --noEmit` clean, **506 tests pass**. All three web steps now gate. | The job itself — it now runs, and a green run is the proof it never had |
| D9 | `completed_at` named in a narrowed select — a `lesson_jobs` column, not `lessons`. Would 42703 `GET /lessons` for every user. | SELF | Column lists must be validated against the migrations. | `test_list_columns_names_no_column_absent_from_the_lessons_table` — **but see D22: this guards one table only** |

### Fixed, in open PR

| ID | Defect | Class | Decision | Enforcement |
|----|--------|-------|----------|-------------|
| D10 | Unpriced model skipped `accumulate_cost` entirely → $3.00 ceiling could never fire | BW | Fail **closed**: charge the most expensive *known* rate, derived from the table; log ERROR; never abort. | `test_cost_ceiling_failopen.py` (PR #105) |
| D11 | `structure_node`'s LLM validation: 6,000-char prompt window vs ≥90%-coverage guard → always discarded above ~6,667 chars | BW | Delete it. Detection is font+regex only, and that is a **limitation, not a feature**. | `test_structure_no_llm.py` (PR #107) — **incomplete, see D12** |

### Review round 2 (2026-07-29) — ALL RESOLVED

Five fixed, one **rejected as a wrong finding**. Kept as its own section because the
shared shape — a guard that watches a *proxy* rather than the property it claims to
prove — is the failure most likely to recur.

These are mine, from today, and they are listed at the same weight as everything else on
purpose.

| ID | Defect | Decision | Enforcement |
|----|--------|----------|-------------|
| ~~D12~~ | **CLOSED 2026-07-29 (PR #107).** Six "no LLM call" assertions spied on `complete_structured` alone; a regression via `provider.complete()` passed all of them. | SELF | Assert on the **factory** — if `get_llm_provider` is never called, no provider method can run. | `factory.assert_not_called()` — **mutation-verified**: "provider obtained but never used" passed the old suite entirely, fails 3 tests now |
| ~~D13~~ | **CLOSED 2026-07-29 (PR #107).** The `chapter` branch was unreachable with the fixture (median 14.0 -> threshold 17.5 -> chapter band starts at 20.125; largest block 18.0pt), so two of three level branches were unpinned dead code. | SELF | Derived font set (24.0/17.0/15.2 against median 12.0) landing one heading in each band. Asserted on `detect_headings` directly, since `coalesce_sections` would make a failure ambiguous. | `test_all_three_heading_levels_are_reachable_from_font_metadata` — catches "chapter branch deleted" and "bands swapped" |
| ~~D14~~ | **CLOSED 2026-07-29 (PR #107).** Golden test was environment-dependent: `STRUCTURE_MAX_SECTIONS=3` turned it red with "detection itself moved" — a misdiagnosis; nothing moved, the cap merged sections. | SELF | Pin `structure_max_sections` and `structure_min_section_chars`, as every neighbouring structure test already did. | The pinned settings in `test_sections_are_identical_to_the_pre_deletion_baseline` |
| ~~D15~~ | **REJECTED 2026-07-29 — the review claim was wrong.** It called `test_fallback_is_at_least_every_known_model_rate` a mathematical tautology ("max over a set is >= every element"). True of the *arithmetic*, but it ignores that the test discriminates *implementations*. **Mutation-tested rather than taken at face value: it catches max->min, output-uses-input-max, AND a hardcoded literal.** Redundant with its neighbour, not tautological. | — | **Keep it.** Deleting a working test on a false premise is worse than keeping a redundant one. Recorded so the claim is not re-raised. | n/a — this entry exists to prevent a wrong "fix" |
| ~~D16~~ | **CLOSED 2026-07-29 (PR #105).** Two defects in one. (a) The story claimed "AC-1 alone would not have caught the original" — **false**: AC-1 asserts `assert_awaited_once()` and the original bug was an early `return` *before* `accumulate_cost`. (b) AC-5's test stubbed `check_ceiling -> True` unconditionally, so it tested the `if` statement, blind to the arithmetic — it could not tell a charge that trips the ceiling from one that does not. | SELF | Correct the claim; run the REAL `accumulate_cost`/`check_ceiling` against fakeredis seeded just under $3.00, with nothing telling `check_ceiling` what to return. | `test_unpriced_charge_really_trips_the_ceiling_via_real_arithmetic` + `test_a_charge_below_the_ceiling_does_not_trip_it` — the two scenarios the stubbed version could not distinguish |
| ~~D17~~ | **CLOSED 2026-07-29 (PR #105).** `None` token counts raised `TypeError: unsupported operand type(s) for /` — an *unknown* exception, so `with_retry` would not retry and the node died. Verified reachable by execution. The call had already succeeded and been billed, so throwing made ARQ re-run and re-pay. Negatives were worse: `accumulate_cost` raises `ValueError` on a negative cost, equally unclassifiable. | SELF | `max(0, x or 0)` at the source, with ERROR/WARNING logs stating the total is now an under-estimate. | `test_missing_token_counts_do_not_crash_the_node` (3 cases) + `test_negative_token_counts_are_clamped_not_propagated` |

### OPEN — live in production

| ID | Defect | Sev | Decision | Enforcement |
|----|--------|-----|----------|-------------|
| **D18** | **`sessions` has zero writers anywhere in `apps/api`** — all 7 references are `.select(...)`. The frontend invents `crypto.randomUUID()`; `assessment/service.py:175` raises **404** if the row is absent. **Quiz and teach-back cannot complete for any student.** Both suites green — Dev 3 seeds the row in tests, Dev 2 mocks the POST. | **Blocker** | Backend must mint the session. Joint Dev 2 + Dev 3 + Dev 4 decision — see Part 4. | *(none — needs a real-DB test)* |
| ~~D22~~ | **CLOSED 2026-07-29.** D9's class was live at 43 sites; replanting it on `sessions` left the suite green. | High | Guard generalised to every table + column, resolving module-level constants. | `test_schema_column_guard.py` — **mutation-verified**: catches the replant both via a literal AND via `_LIST_COLUMNS` |
| **D29** | **DPDP `user_consents` audit table has zero writers.** Migration `20260702000000_dpdp_user_consents.sql` genuinely creates the table, RLS, and a trigger syncing `users.attention_consent` — but `process_onboarding()` (`apps/api/app/modules/assessment/service.py:864-976`) never inserts into it. CLAUDE.md §18 names this table an explicit **Sprint 2 priority** precondition before any attention data is collected — schema shipped, the actual consent-write path was never built. Found 2026-07-29 during a cross-team Sprint 2 completion audit (`docs/sprint2-completion-audit-2026-07-29.md`); re-verified 2026-07-30 that no write path landed since. | High (compliance) | **Needs Dev 3.** Write a `user_consents` row (consent_type, policy_version, consented_at) at the point onboarding consent is captured, before Sprint 3's `AttentionMonitor` can legally initialize. | *(none — grep for `user_consents` in `apps/api` only matches a migration-name string in a test assertion)* |
| **D30** | **3 tests failing on `main`** in `apps/api/tests/test_tutor_service.py`: `test_two_below_threshold_no_cooldown_dispatches`, `test_intervention_delivers_tutor_intervene_message`, `test_intervention_no_delivery_on_cache_miss`. Root cause: `service.py:328` added a `state_raw == "TEACHING"` guard on the CES-trigger check (itself correct — CLAUDE.md §10, CES monitoring only active in TEACHING), but the tests' mock Redis never returns `"TEACHING"` for `tutor_state:sess-1`, so the guard now silently blocks the trigger the tests assert on. Reproduced live via `pytest .venv` on 2026-07-29 and re-confirmed live on 2026-07-30 against current `main` (3 failed, exact same assertions). | Med (currently red on `main`) | **Needs Dev 4.** Update the mock Redis fixtures in `test_tutor_service.py` to return `"TEACHING"` for the relevant session key, matching the real guard's precondition — the guard itself is correct, don't touch it. | The 3 named tests themselves — currently failing, will pass once fixtures are updated |

### OPEN — found by the 2026-07-30 frontend wiring audit

Full report and the ~40 lower-severity items: **`docs/reports/frontend-wiring-audit-2026-07-30.md`**.
D31-D33 are **Dev 1's own**, found *after* Dev 1 declared its work finalized.

| ID | Defect | Sev | Decision | Enforcement |
|----|--------|-----|----------|-------------|
| **D31** | **`NEXT_PUBLIC_API_URL` omits the `/api` segment in every Dev-1-owned source, so following the setup documentation 404s every API call.** `apps/web/src/lib/api.ts:4` falls back to `http://localhost:8000/api` (correct), but `.env.example:10`, `.github/workflows/ci.yml:126` and `docs/handoffs/dev2-handoff-2026-07-29.md:154` all say `http://localhost:8000`. Verified empirically: axios joins that with `content/lessons` to give `/content/lessons`, and `main.py:166-172` mounts every router under `/api` with **no unprefixed alias**. A dev who configures nothing works; a dev who reads the docs, or runs a CI build, is dead on arrival. Two other docs have it right — the repo contradicts itself in six places. | High | Pick one convention and fix all sources. **Enforcement must be executable**: three independent verifier agents reached three different verdicts on whether this blocks generation, which is exactly what a test settles and prose does not. | *(to add — assert the resolved URL for a known route ends in `/api/content/lessons`)* |
| **D32** | **`_group_by_segment_id` does a raw `item["data"]` subscript** (`graph.py:3856`) while its docstring claims *"Same defensive-skip philosophy as `_index_by_segment_id`"*. It guards `segment_id` and then subscripts blind, so one entry lacking `data` raises `KeyError` and kills `package_builder_node` — **the last node, after 100% of the lesson's LLM/TTS/image spend**. | Med | Apply the defensive skip the docstring already promises. **This is site 2 of a defect closed at site 1** (`_index_by_segment_id`, Story 2-31) — binding rule 6: wrong at site 2 means the pattern, not the instance, needed fixing. | *(to add)* |
| **D33** | **`book_id`/`chapter_id` default to `""` against `UUID` fields.** `graph.py:711,3742` use `or ""` / `.get(..., "")`; `schemas/lesson.py:212-213` declare `UUID`. An empty string can never satisfy that, so a missing `chunk` output surfaces as a bare Pydantic `ValidationError` at the final node — after full spend — instead of a diagnostic naming the actual cause. | Low | Raise an explicit diagnostic that names the missing upstream output. | *(to add)* |
| D34 | **`lesson_ready` is routed with the wrong key type.** `core/pubsub.py:67,80` strips the `lesson_ready:` prefix and passes the resulting **lesson_id** into `manager.send()`, which keys connections by the path-param **session_id** (`websocket.py:72,110`). The `lesson_waiters:{lesson_id}` set Dev 4 described does not exist in `apps/api`. | Med | Dev 4 owns the SADD/SMEMBERS fan-out. **Not currently load-bearing**: `useLessonSocket.ts:50-55` deliberately no-ops `lesson_ready` and readiness comes from REST polling — so this is dead code, not an outage. | *(to add — assert `manager.send` receives an id a client actually connected under)* |
| D35 | **`setSessionId` has no caller.** `player.machine.ts:146` mints `sessionId: crypto.randomUUID()` and nothing ever replaces it, so the id sent to every session-scoped assessment route was never persisted. The frontend half of D18. | High | Dev 2 calls `setSessionId(server_session_id)` from the response to `POST /api/assessment/sessions` (PR #119) before the player can reach QUIZZING/TEACH_BACK. | *(to add — gate quiz submission on a server-issued id)* |
| D36 | **Stack drift, unowned: `apps/web` is Next 16.2.9 / React 19.2.4 while `CLAUDE.md` locks "Next.js 14 + TypeScript + Tailwind".** Two major versions. Nobody was tasked with reconciling it, and it may silently invalidate other Next-14-shaped assumptions in the frontend and in this document. | Med | Either amend the locked stack in `CLAUDE.md` (a stack change needs the §16-style four-dev conversation) or pin back. **Do not leave the two disagreeing** — `CLAUDE.md` is declared the source of truth, so a divergence makes it untrustworthy generally. | DISCIPLINE — needs an owner first |
| ~~D37~~ | **CLOSED 2026-08-04.** **`_LIST_COLUMNS`' PostgREST JSON-path selectors have never been executed against real Postgres.** `subject:content->metadata->>subject` and the `estimated_duration_mins` sibling (`content/router.py:112-116`) are exercised only against Supabase mocks. **The `completed_at` reference in this exact select list already caused one outage-class `42703`** (D9), and per binding rule 4 a mock has no Postgres catalog and cannot raise it. | Med | One integration test against real PostgREST covering this select. Until then `GET /lessons` is unverified against the database it queries. | `tests/integration/test_book_select_lists_against_postgrest.py` — runs every select list the app sends against a real PostgREST, including `_LIST_COLUMNS`. Carries a live-trap premise test asserting a bogus column really does raise 42703, so it cannot pass vacuously. **9 passed 2026-08-04.** |
| ~~D38~~ | **CLOSED 2026-08-03.** ~~The book-scale Phase 2 migration has never touched the real Supabase project.~~ Applied to the live project and verified there: both columns present, `chapters.lesson_id` now nullable per the live OpenAPI schema, 23/23 backfilled to `fallback`, row counts unchanged, 0 duplicates. RLS confirmed with real minted JWTs — owner sees 9 chapters / 1,507 chunks, stranger 0, anon 0, matching the ownership graph exactly. Original text: `20260803000000_chapters_book_scoped.sql` is verified only against a PostgreSQL 16 container plus a hand-written Supabase shim (`apps/api/tests/integration/supabase_shim.sql`), which reproduces the *contract* of `auth.users` / `auth.uid()` / `storage.buckets` / the `anon`,`authenticated`,`service_role` roles — not Supabase's implementation. Every RLS verdict in that suite is conditional on the shim being faithful, and no test in this repo can disconfirm it (binding rule 2). | Med | Dev 1 applies the migration to the real project and re-runs the RLS assertions there. **Trigger: before Phase 3 writes any chapter row to a real database.** Until then Phase 2 stays `🧪 Implemented`, never `✅ Verified`. | `# MOCK-CONTRACT:` marker on `test_shim_auth_uid_reads_jwt_claims` naming this ID |
| ~~D39~~ | **CLOSED 2026-08-03.** ~~The duplicate `(book_id, chapter_index)` pre-flight was run against an empty container, not production.~~ Live project queried read-only: **23 chapters, 23 distinct books, every `chapter_index=1`, 0 duplicates**. The migration was then rehearsed over a production-shape copy and applied cleanly with all row counts intact. Original text: Story 1-9 AC10 requires the migration to fail loudly rather than discard data if duplicates already exist; that behaviour is now proven (`test_migration_aborts_loudly_on_preexisting_duplicates`), but whether the real database *contains* duplicates is unknown. The tracker expects 23 chapter rows, all written by the hardcoded `chapter_index: 1` path (`graph.py:624`) — so any book with two ingestions would collide. | Med | Query the real `chapters` for duplicate pairs before applying. **Trigger: the apply itself** — the migration aborts atomically (`BEGIN/COMMIT`), so a collision is loud and recoverable, but it will block the deploy. | Migration is atomic + `test_aborted_migration_destroys_no_data_and_leaves_no_partial_schema` |
| D40 | **`tests/integration` leaks state into `tests/test_dna_growth.py`.** Running the integration suite first fails 18 of the 21 dna_growth tests; they pass in isolation. Reproduced identically on `main` via a git worktree, so it predates the book-scale work. This is the bulk of the 19 failures in CI's advisory `pytest tests -q` step (D24). | Med | Dev 3 owns `learner_dna`. The leak is in module-scope state, not in the migration work. **Trigger: the D24 ratchet** — these 19 must reach zero before `continue-on-error` can be dropped. | *(to add — isolate the fixture that leaks)* |
| D41 | **`POST /api/content/lessons` changes shape and `apps/web` cannot generate a lesson until Phase 6.** Upload returns `{book_id}` instead of `{lesson_id}` and 422s on `tier`. `UploadFlow.tsx:74-79,155-157` sends `tier` on **100 %** of uploads (mode selection is the only path to `processing`), so it fails at the first click; with no tier it polls `content/lessons/undefined` forever. The replacement write endpoint is Phase 6, three phases later. | Med | **The change never reaches `main` until Phase 7.** All of Phases 3–6.5 and Track W land on `book-scale/integration`; `main` keeps its working `POST /lessons` meanwhile. Dev 2 is told before merge, not after. **Trigger: merge of `book-scale/integration` to `main`.** | Track W's W0 contract CI job fails when the committed `docs/contracts/book-api.v1.json` and the live FastAPI schema diverge |
| D42 | **Book ingest is dominated by the Storage download, not by detection.** Measured on the Phase 3 gate against the live project: ingest of a 44.7 MB / 1,151-page book took **28.4 s**, of which **18.9 s (67 %) was downloading the source at 2.4 MB/s** and 10.1 s was processing. AC15's 15 s budget came from Phase 1, which measured `get_toc()` + text sweep on a **local** file and never included the fetch. | Low | AC15 split into processing (met, 10.1 s) and end-to-end (recorded, not capped) rather than moving the number until it passed. Transfer cost is environment-dependent — this was a dev machine to a remote Supabase. **Trigger: the India-region migration** (CLAUDE.md already requires it before Sprint 3), or the first user complaint about upload latency. | Numbers recorded in the tracker's Phase 3 Observed result; re-measure from a co-located worker after the region migration |

---

### OPEN — accepted, with a named trigger

Not "documented limitations". Each carries an explicit condition that reopens it.

| ID | Defect | Sev | Decision | Enforcement |
|----|--------|-----|----------|-------------|
| D21 | Embed truncation assumes ~4 chars/token. Measured `cl100k_base`: English 6.0, **Hindi 1.06, Tamil 0.71** | Deferred | **DECISION 2026-07-29: English-only for now.** Fix is one line and already specified (plan 6.3): `enc.decode(enc.encode(text)[:cap])`. **Trigger: the first Indic-language lesson.** | DISCIPLINE — comment at `graph.py` truncation site |
| D28 | **`detect_headings` ranks a chapter BELOW its own subsections.** `candidates` is keyed by text and every writer is guarded by `if text not in candidates`, so the **font strategy always beats the regex strategies that run after it** — an explicit `Chapter N:` prefix loses to a relative font-size band. Visible in the golden baseline: `Chapter 1` at `level: "topic"`, its own `1.1`/`1.2` at `"section"`, while `_LEVEL_RANK = {chapter: 0, section: 1, topic: 2}`. | Med | **DECISION 2026-07-29: pinned, NOT fixed.** Changing precedence is a detection *behaviour* change, and Story 2-34's entire premise is that removing an inert LLM call is behaviour-**preserving**. **Trigger: the Sprint 3 docling migration**, per the decision to park structure detection. | `test_font_strategy_wins_over_the_chapter_regex_inverting_the_hierarchy` pins the WRONG behaviour with re-capture instructions — the fix cannot land silently |
| D24 | **CI's new test steps land ADVISORY (`continue-on-error: true`), not gating.** `pytest tests` surfaces 22 pre-existing failures (Dev 3: 19, Dev 4: 3). Gating it on day one turns `main` red for all four developers over failures this PR did not introduce. **Applies to the api job only** — `pnpm test` was measured green (D25) and gates from day one. | Med | **DECISION 2026-07-29: land advisory, ratchet later.** `tests/unit` + `tests/integration` **do** gate (and `-x` is gone, so CI now enumerates rather than stops at one). **Trigger to drop `continue-on-error`:** the 22 reach zero. Until then the number is *visible*, which it has never been. **Concrete instance, 2026-07-29:** the D23 fix (PR #113) broke `test_lesson_ready_pubsub.py`, which lives in root `tests/` and asserted the pre-D23 contract. Dev 1 measured "no regression" against the GATING scope only and merged it. The advisory step would have shown 23 instead of 22 — visible, but not blocking. This is the cost of the compromise, paid within the hour, and it is the strongest argument for the trigger. | DISCIPLINE — the trigger is in a comment at both step definitions in `.github/workflows/ci.yml` |
| D26 | **CI has failed on 60 of its last 60 runs — zero successes — and merges proceeded anyway.** The API job dies at `ruff check .` (31 errors: Dev 3 22, Dev 4 9), which is *before* any test step, so "CI skipped the root `tests/` directory" understates it: **CI never reached a test step at all.** The web job died even earlier (D25). | SELF/BW | A red gate that everyone routes around is worse than no gate — it trains the team to ignore it. Gating scope must be a set that is green *today* (`tests/unit` + `tests/integration`: 743 pass) and grows by ratchet. | **PARTIALLY RESOLVED 2026-07-29, run 30470590163.** The **web job passed completely for the first time in the repo's history** — install, lint, type-check, 506 tests, and `build`. The API job now clears `ruff check` and `ruff format --check` (Dev 4 #a1ebbbe, Dev 3 #115, Dev 1 #117) and dies at the **next** gate, `mypy app`: 24 errors — Dev 3 19, Dev 4 5. **That is now the single thing between this repo and a fully green CI.** Each gate cleared reveals the next; the count was never one number |

---

## Part 3 — Process defects

| ID | Defect | Decision | Enforcement |
|----|--------|----------|-------------|
| ~~P1~~ | **CLOSED 2026-07-29.** CI skipped the root `tests/` dir and used `-x`. | Now `pytest tests -q`. **Clear-eyed: this would not have caught one of the 17** — those tests are mock-shaped too. Observability only. | `.github/workflows/ci.yml` |
| ~~P2~~ | **CLOSED 2026-07-29.** The web job never ran tests; 41 story lines claimed "488 tests green" that no machine had verified. | `pnpm test` added before `build`. | `.github/workflows/ci.yml` |
| P3 | `docs/deferred-work.md` is 6 lines with **0 items**, against 131 defer markers | Superseded by this file. Deferral is only valid with an ID, an owner and a **trigger condition**. | DISCIPLINE + review checklist |
| P4 | `CLAUDE.md` mandates 5 review layers; the skill ships 3. Every PR to date shipped 3 under a document saying REJECT under 5. | Add Story Quality + Process Integrity to the skill, or amend CLAUDE.md to match reality. **Do not leave the two disagreeing.** | *(to add)* |
| P5 | Every AC said "no new findings on any **touched** file"; CI checks repo-wide. Both were satisfiable while 78 repo-wide errors accumulated. | **ACs must state repo-wide numbers.** Already applied from Story 2-33 onward. | Review checklist |
| P6 | RC-1. The anti-deadlock mocking rule has no expiry clause. | See Part 4. | — |

---

## Part 4 — Binding decisions going forward

These are the rules. Each says how it is enforced.

**BD-1 — Verification scope must equal CI scope.**
An AC may not scope a gate to touched files. State the repo-wide number and `main`'s number.
*Enforcement: review checklist. `DISCIPLINE` until a lint on story files exists.*

**BD-2 — A test may not assert only on a mock it constructed.**
Every test asserts an observable outcome, or is marked `# MOCK-CONTRACT:` naming the
real-dependency test that covers the same path. This is RC-1, which explains 12 of 17.
*Enforcement: `DISCIPLINE` today. Becomes machine-checkable once BD-3 lands.*

**BD-3 — One CI job runs against real dependencies.** *(highest leverage — do this first)*
`postgres:16 + pgvector` with all 9 migrations applied, no Supabase fake, and provider tests
raising genuine `openai` / `httpx` / `redis` exception objects.
It is the only change that attacks RC-1 and RC-2 at once. It kills D9's whole class (43
sites), D19, D20, and would have caught D3, D4, D5, D6, D8.
*Enforcement: the job itself.*

**BD-4 — Any `except SomeLib.Error` requires an executable premise assertion.**
D3, D6, D19 and D20 are all the same defect: we assumed a type hierarchy. `test_retry.py`
already models this with `test_openai_exceptions_are_not_httpx_derived`.
*Enforcement: named test per library.*

**BD-5 — A documented limitation is not an accepted one.**
A `KNOWN LIMITATION` / `TODO` / `FIXME` comment must carry a `D-nn` register ID. A comment
without an ID is a defect, not a decision. D11 sat behind such a comment for multiple
sprints and survived every review *because it was known*.
*Enforcement: grep gate in CI — `DISCIPLINE` until written.*

**BD-6 — Golden fixtures pin their environment and name their capture commit.**
D13/D14. A baseline that moves with an env var is not a baseline, and one that freezes a
defect is worse than none.
*Enforcement: convention + review. `DISCIPLINE`.*

**BD-7 — "Matches existing accepted pattern" is not a justification.**
It is the ratchet that took `{**state, ...}` from 1 site to 18. If the pattern is wrong at
site 19, it was wrong at site 1; open a register entry.
*Enforcement: `DISCIPLINE` — review checklist.*

**BD-8 — The mocking rule gets an expiry.**
CLAUDE.md's *"each dev mocks the other's interface"* stays for scheduling, but every mocked
cross-dev contract needs one real integration test before Sprint 3 real-student launch. D18
is what happens without it: three developers, three green suites, one broken product.
*Enforcement: BD-3 + a per-contract checklist.*

---

## Scorecard

| | Count |
|---|---|
| Defects closed (fixed **and** guarded) | **22** |
| Fixed, awaiting merge | **0** — everything Dev 1 owns is on `main` |
| **Open** | **16** |
| Of which **live in production** | **4** — D18 (awaiting Dev 3's review of PR #119), D29 (DPDP consent row, Dev 3), **D31** (env prefix, Dev 1), D35 (`setSessionId`, Dev 2) |
| Of which **self-inflicted 2026-07-29** | **0** — all six resolved (5 fixed, D15 rejected as a wrong finding) |
| Of which **found by the 2026-07-29 cross-team Sprint 2 completion audit** | **2** (D29, D30) — `docs/sprint2-completion-audit-2026-07-29.md` |
| Binding decisions relying on `DISCIPLINE` alone | **5 of 8** |
| Open entries with a named owner **and** a trigger | **15 of 16** (D36 has no owner) |
| Found by the 2026-07-30 wiring audit | **7** registered (D31–D37), ~40 more in the report |
| Found by the 2026-08-03 Story 1-9 five-agent review | **3** registered (D38–D40); **D38 and D39 both closed same day**|
| Found by the 2026-08-04 book-scale UI re-plan and Phase 3 gate | **2** registered (D41, D42) |

That last row is the honest health metric. Five of eight rules currently depend on someone
remembering. **BD-3 is the one that converts the most of them into machine checks, which is
why it is first.**
