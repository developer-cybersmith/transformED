# Sprint 4 Pre-existing Test Failure Report

**Date:** 2026-08-31
**Branch audited:** `master-sprint4-dev3`
**Reported by:** Dev 3 (tannmayygupta)
**Full suite result:** 223 FAILED · 66 ERROR · 2100 passed · 34 skipped

---

## Summary by Developer

| Developer | FAILEDs | ERRORs | Root Cause Category | Status |
|-----------|---------|--------|---------------------|--------|
| **Dev 3** | 22 | 0 | Stale mock chains + obsolete assertions | **FIXED in this PR** |
| **Dev 1** | 187 | 66 | Unimplemented endpoints / missing `tinytag` dep / auth cascade | **ACTION REQUIRED** |
| **Dev 4** | 12 | 0 | JWT 403→401 / Redis key mismatch / PubSub bugs | **ACTION REQUIRED** |
| Integration | 2 | 0 | Real `OPENAI_API_KEY` required | Skip in unit CI |

---

## Dev 3 Fixes (Completed — Story 4-10)

All 22 Dev 3 failures were pre-existing stale test assertions. Fixed in
branch `sprint4/s4-dev3-preexisting-test-fixes`, merged into `master-sprint4-dev3`.

### Fix 1 — `tests/test_session_report_endpoint.py` (18 failures)

**Root cause:** `_build_report_supabase` helper set up Supabase mock chains for old DB
call shapes (no `.limit()`, no `.order()`). The service layer had evolved — adding
`.limit(500)` on `quiz_attempts`, `.order().limit(50)` on `teachback_attempts`,
`.order().limit(20)` on intervention rows, and `.limit(20)` on `dna_update` events —
but the test helper was never updated. MagicMock auto-creates new attribute chains,
which return auto-MagicMock objects with `len() == 0`, causing `total_quiz = 0` and
`quiz_accuracy_label = None` across the board.

**Fix applied:**
- Call 3 (quiz_attempts): `.select().eq()`.limit(500).execute()`
- Call 4 (teachback_attempts): `.select().eq().order().limit(50).execute()`
- Call 6 (intervention rows): `.select().eq().eq().order().limit(20).execute()`
- Call 8 (dna_update events): `.select().eq().eq().limit(20).execute()`
- `test_get_report_ces_score_null_returns_zero`: updated assertion from `== 0.0` to
  `is None` — the service deliberately returns `None` for empty CES history to let
  the frontend distinguish "no data" from "genuine zero engagement".

### Fix 2 — `tests/test_s3_35_session_finalization.py` (2 failures)

**Root cause:** Both failures were stale assertions against a design that changed via D116.

- `test_finalize_session_updates_sessions_table`: asserted `ended_at` IS in the payload.
  D116 decision: `_finalize_session` writes ONLY `ces_final`; `complete_session` REST
  endpoint owns `ended_at`. Writing `ended_at` again would clobber the real timestamp.
- `test_finalize_session_ces_final_zero_when_no_history`: asserted `ces_final == 0.0`.
  Implementation writes `None` for empty Redis history (distinguishes "no data" from
  "student genuinely scored zero").

**Fix applied:** Updated both assertions to match D116 implementation with inline doc.

### Fix 3 — `tests/test_s3_42_ces_breakdown_accuracy.py` (1 failure)

**Root cause:** `inspect.getsource(get_session_report)` used to check for
`settings.ces_weight_behavioral`. The weights live in `_build_ces_breakdown` (lines
816–834 of `service.py`), which is called by `get_session_report` but the strings
don't appear in `get_session_report`'s own source.

**Fix applied:** Changed `getsource` target to `_build_ces_breakdown`.

### Fix 4 — `tests/test_posthog_events.py` (1 failure)

**Root cause:** Two issues:
1. `SessionReport` constructor missing two required Pydantic fields added in Story 3-47:
   `formula_applied` and `signal_coverage`.
2. `app/modules/assessment/router.py` line 232 calls `get_redis()` in the route handler
   body before calling `get_session_report`. The test mocked `get_session_report` but
   not `get_redis()`, causing `RuntimeError: Redis pool is not initialised`.

**Fix applied:** Added both missing fields to the `SessionReport` constructor; added
`patch("app.core.redis.get_redis", return_value=MagicMock())` inside the test.

---

## Dev 1 Failures — Action Required

**Owner:** Dev 1 (Infra, content pipeline, all 11 nodes)
**Total:** 187 FAILED + 66 ERROR

### Root Cause A — Auth cascade: 66 ERRORs in admin/content/media router tests

**Affected files:**
- `tests/unit/test_admin_router.py` — 41 ERRORs
- `tests/unit/test_content_router.py` — 12 ERRORs
- `tests/unit/test_media_router.py` — 13 ERRORs

**Root cause:** All 66 errors are `AssertionError` during test **setup** (collection
or fixture creation), not test execution. The auth fixture for these tests uses Dev 4's
JWT middleware. Dev 4's auth router returns HTTP 204 with a response body — a violation
of RFC 9110 (204 responses MUST NOT have a body). The middleware raises an `AssertionError`
in the ASGI layer during fixture creation, causing the entire router's test module to
error before any test runs.

**Fix required (Dev 4):** Auth router must return `Response(status_code=204)` with no
body, OR the fixture must be updated to not trigger the body check. This is Dev 4's bug
(auth router) but cascades into all of Dev 1's router tests.

**Specific error pattern:**
```
AssertionError: Response with status code 204 should not have a body
```

### Root Cause B — Unimplemented content pipeline: 187 FAILEDs across 7 files

These are tests written RED-first by Dev 1 — they are expected to fail until Dev 1's
implementation lands. They are NOT regressions from Sprint 4 work.

#### `tests/unit/test_book_endpoints.py` — 39 FAILED

**What these test:** `GET /api/content/books`, `GET /api/content/books/{id}`,
`GET /api/content/books/{id}/chapters` endpoints that list a user's books and chapters
with proper ownership scoping, pagination, and malformed-UUID rejection.

**Why failing:** The book-listing and chapter-listing endpoints are partially or fully
unimplemented. Tests assert on response shape, column selection, N+1 query guards,
malformed UUID rejection (returns 404 not 422), and security (other user's book is 404
not 403).

**Fix required:** Implement `list_books`, `get_book`, `list_chapters` route handlers in
`apps/api/app/modules/content/router.py` with proper ownership scoping (`.eq("user_id",
user_id)` on every query), bounded DB reads, and 404 on malformed UUID (validate UUID
before hitting DB).

**Representative failures:**
```
FAILED tests/unit/test_book_endpoints.py::test_list_books_returns_the_documented_shape
FAILED tests/unit/test_book_endpoints.py::test_get_book_ownership_is_rechecked_even_if_the_row_comes_back
FAILED tests/unit/test_book_endpoints.py::test_list_chapters_lessons_field_capped_at_20_newest_lesson_count_unaffected
FAILED tests/unit/test_book_endpoints.py::test_book_embed_targets_a_real_relationship
```

#### `tests/unit/test_content_router.py` — 37 FAILED

**What these test:** `POST /api/content/upload`, `GET /api/content/lessons/{id}`,
`GET /api/content/lessons` endpoints — upload flow, status checking, lesson retrieval,
signed URL generation, and metadata field handling.

**Why failing:** The content router has partial implementations. Tests assert on exact
response shapes, Supabase column selects (narrow — not `*`), signed URL resolution,
content-null handling, non-finite duration dropping, non-string subject dropping,
and rate limiting.

**Fix required:** Complete content router implementation: upload flow (book creation +
book_ingest job enqueue, not lesson pipeline), lesson GET with signed URL resolution,
lesson LIST with narrow column select, proper subject/duration sanitisation.

**Representative failures:**
```
FAILED tests/unit/test_content_router.py::test_upload_creates_a_book_and_no_lesson
FAILED tests/unit/test_content_router.py::test_list_lessons_selects_narrow_columns_not_star
FAILED tests/unit/test_content_router.py::test_non_finite_duration_is_dropped_not_serialised[NaN]
FAILED tests/unit/test_content_router.py::test_embedded_media_expiry_covers_a_realistic_study_session
```

#### `tests/unit/test_generate_lesson_endpoint.py` — 83 FAILED

**What these test:** `POST /api/content/books/{book_id}/chapters/{chapter_id}/generate`
endpoint — the lesson generation trigger. Tests cover book ownership validation, chapter
ownership, malformed UUID rejection, tier handling, span gate (40-chapter cap), concurrency
cap (429), idempotency (existing lesson returned as 200), `lesson_jobs` pre-creation,
ARQ enqueue, rollback on enqueue failure, rate limiting (3/min + hourly), and
storage key layout.

**Why failing:** The generate endpoint is partially or not implemented. This is the most
test-dense area of Dev 1's work.

**Fix required:** Implement `POST .../generate` in `apps/api/app/modules/content/router.py`
with:
- UUID validation (404 before DB for malformed IDs)
- Book ownership check (`.eq("user_id", user_id)` + 404 if absent/wrong)
- Chapter ownership check (`.eq("book_id", book_id)` + 404 if absent/wrong)
- Span gate: `end_chapter - start_chapter + 1 <= 40` → accept; > 200 → 422
- Concurrency cap: count `generating` rows for this user; ≥ cap → 429
- Idempotency: return existing `generating`/`ready` lesson as 200 (unless `force=True`)
- `lesson_jobs` row created BEFORE enqueue (FK order)
- ARQ enqueue with `pipeline_content` job name + retry-safe key
- Rollback (delete `lesson_jobs` then `lessons` in FK order) on enqueue failure
- Rate limit keyed on `user_id`, NOT `request.client.host` (IP is shared behind egress)

**Representative failures:**
```
FAILED tests/unit/test_generate_lesson_endpoint.py::test_generate_route_is_registered_on_the_real_app
FAILED tests/unit/test_generate_lesson_endpoint.py::test_at_the_concurrency_cap_the_request_is_429_with_retry_after
FAILED tests/unit/test_generate_lesson_endpoint.py::test_rollback_deletes_lesson_jobs_then_lessons_in_fk_order
FAILED tests/unit/test_generate_lesson_endpoint.py::test_generate_route_keys_its_bucket_on_the_user_not_the_request_ip
FAILED tests/unit/test_generate_lesson_endpoint.py::test_a_stale_generating_lesson_does_not_block_regeneration
```

#### `tests/unit/test_eval_runner.py` — 3 FAILED

**What these test:** The eval runner script that exercises PDF extraction fixtures
(`scripts/eval_runner.py` or similar). Tests assert on PDF fixture categories, page
count boundaries, and failure isolation.

**Why failing:** Eval runner script missing or not wired to the expected import path.

**Fix required:** Locate or implement the eval runner at the path the tests import from.
Check if `tests/unit/test_eval_runner.py` imports from a module that hasn't been created
yet.

**Failures:**
```
FAILED tests/unit/test_eval_runner.py::test_run_all_evals_isolates_per_pdf_failures_and_writes_results
FAILED tests/unit/test_eval_runner.py::test_run_all_evals_truncates_stale_progress_file
FAILED tests/unit/test_eval_runner.py::test_eval_pdf_keys_matches_generator_keys_exactly
```

#### `tests/unit/test_extract_page_bounds.py` — 1 FAILED

**What this tests:** Named PDF eval fixtures exist on disk.

**Why failing:** Eval fixture files not present in the repo's test data directory.

**Failure:**
```
FAILED tests/unit/test_extract_page_bounds.py::test_all_named_eval_fixtures_actually_exist
```

**Fix required:** Add PDF fixtures under the path the test expects (check the test for
the expected directory), OR mark the test `@pytest.mark.skip` if fixtures are too large
for the repo.

#### `tests/unit/test_node_return_shape.py` — 1 FAILED

**What this tests:** TTS node returns ONLY its own state keys (not `{**state, ...}`).
This is the **anti-spreading guard** (CLAUDE.md binding rule: "A LangGraph node must
return ONLY the state keys it owns").

**Why failing:** The TTS node implementation spreads `**state` in its return dict,
violating the binding rule. The source-scan guard catches it.

**Failure:**
```
FAILED tests/unit/test_node_return_shape.py::test_tts_node_returns_only_its_own_keys
```

**Fix required (CRITICAL):** In `apps/api/app/modules/content/pipeline/nodes/tts_node.py`,
change the return statement from `return {**state, "narration_scripts": ...}` to
`return {"narration_scripts": ...}` (return only the keys owned by this node).
This is a binding rule violation — the node will double all accumulated channels on
every retry.

#### `tests/unit/test_tts_node.py` — 22 FAILED

**What these test:** TTS node functional behaviour — Sarvam/Azure/browser fallback chain,
cost ceiling enforcement, idempotency cache, checkpoint writes, narration cap truncation,
DPI rendering, error degradation per segment (not full node failure), upload upsert.

**Why failing:** `ModuleNotFoundError` on `tinytag` — this library is used by `tts_node.py`
but is NOT listed in `apps/api/pyproject.toml` `[project.dependencies]`.

**Fix required:**
1. Add `tinytag` to `apps/api/pyproject.toml` under `[project.dependencies]`.
2. Run `pip install -e ".[dev]"` to pick up the new dependency.
3. Re-run `tests/unit/test_tts_node.py` — some tests may then fail for other reasons
   (implementation gaps), but the `ModuleNotFoundError` cascade will be resolved.

**Note:** After fixing the import error, tests may still fail if `tts_node.py` itself
has bugs. The 22 failures include both the import error AND potential logic bugs under
the import error.

**Representative failures:**
```
FAILED tests/unit/test_tts_node.py::test_happy_path_sarvam_success_produces_nested_narration_entries
FAILED tests/unit/test_tts_node.py::test_over_ceiling_skips_paid_providers_and_downshifts_to_browser
FAILED tests/unit/test_tts_node.py::test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments
FAILED tests/unit/test_tts_node.py::test_narration_cap_truncation_does_not_split_devanagari_combining_mark
```

---

## Dev 4 Failures — Action Required

**Owner:** Dev 4 (WebSocket handlers, JWT middleware, 7-state tutor, Redis buffer)
**Total:** 12 FAILED

### Root Cause A — Auth router 204 body violation (cascades to Dev 1 ERRORs)

**Affected:** Not Dev 4's own test files, but it is Dev 4's code that causes it.
See "Root Cause A" under Dev 1 above. Dev 4's auth router returns HTTP 204 with a body
(violates RFC 9110). This is also the root cause of 66 ERRORs in Dev 1's test suite.

**Fix required:** In `apps/api/app/modules/auth/router.py`, change the logout/signout
response to return `Response(status_code=204)` with no body content.

### Root Cause B — JWT middleware returns 403 instead of 401 (4 FAILED)

**Affected files:**
- `tests/test_session_create_endpoint.py::test_unauthenticated_request_is_rejected` (1)
- `tests/test_tutor_router.py::test_get_session_state_enforces_jwt_ac3` (1)
- `tests/test_tutor_router.py::test_post_intervene_enforces_jwt_ac11` (1)

**Root cause:** The JWT verification middleware (or Supabase dependency) returns HTTP 403
when no token or an invalid token is supplied. RFC 9110 requires **401 Unauthorized** for
"missing or invalid credentials" and 403 for "authenticated but not authorised".
Tests assert `== 401`; middleware returns `== 403`.

**Specific assertion error:**
```
assert 403 == 401
```

**Fix required:** In `apps/api/app/dependencies.py` (or wherever the JWT `verify_token`
dependency lives), change the `HTTPException(status_code=403, ...)` for missing/invalid
tokens to `HTTPException(status_code=401, detail="...", headers={"WWW-Authenticate": "Bearer"})`.
403 should only be raised when the token is valid but the user lacks permission for the
specific resource.

**Security note:** `test_auth.py::test_alg_none_token_rejected` returns 500 instead of
401 — this is a **security-critical** failure. An `alg: none` JWT must be rejected with
401 (not crash with 500). Crashing on a crafted token could be exploited for DoS.

**Failure:**
```
FAILED tests/test_auth.py::test_alg_none_token_rejected — assert 500 == 401
```

**Fix required:** The JWT decode path must catch the `alg: none` variant explicitly.
In `apps/api/app/dependencies.py` (or the JWT helper), add `algorithms=["HS256"]` (or
the actual allowed algorithm) to `jwt.decode()` and ensure that any `DecodeError`
returns 401, not 500.

### Root Cause C — Tutor state machine Redis key mismatch (3 FAILED)

**Affected file:** `tests/test_tutor_graph.py`

**Failing tests:**
```
FAILED tests/test_tutor_graph.py::test_fatigue_blocked_when_already_fired_stays_teaching
FAILED tests/test_tutor_graph.py::test_fatigue_detected_sets_fatigue_fired_flag
FAILED tests/test_tutor_graph.py::test_fatigue_fires_once_then_blocked
```

**Root cause:** The fatigue state tests use a specific Redis key pattern (e.g.,
`fatigue_fired:{session_id}`) but the implementation uses a different key pattern or
doesn't set/read the key consistently. Tests mock Redis with an expected key that doesn't
match the actual implementation key.

**Assertion pattern:**
```
AssertionError: Redis key 'fatigue_fired:ses-xxx' was expected to be set but wasn't
```

**Fix required:** Audit `apps/api/app/modules/tutor/state_machine/graph.py` — check what
Redis key name `_detect_fatigue` or `_block_fatigue` uses. Update either the
implementation or the test mock to use the same key name consistently. The CLAUDE.md
binding rule says "fatigue ONCE per session (Redis flag)" — the flag key must be
documented and consistent.

### Root Cause D — PubSub subscriber implementation bugs (3 FAILED)

**Affected file:** `tests/test_lesson_ready_pubsub.py`

**Failing tests:**
```
FAILED tests/test_lesson_ready_pubsub.py::test_subscriber_forwards_pmessage_to_manager
FAILED tests/test_lesson_ready_pubsub.py::test_subscriber_caches_lesson_package
FAILED tests/test_lesson_ready_pubsub.py::test_publish_key_ignores_a_session_id_that_cannot_exist
```

**Root cause:** The Redis PubSub subscriber that forwards `lesson_ready` events to the
WebSocket connection manager has implementation bugs. Tests assert that:
1. A `pmessage` received on the `lesson_ready:{session_id}` channel is forwarded to the
   connection manager
2. The `LessonPackage` is cached after the message is received
3. Malformed/non-existent session IDs in the publish key are ignored (not forwarded)

**Fix required:** Audit `apps/api/app/core/pubsub.py` or wherever the lesson-ready
subscriber lives. Check:
- That the subscriber correctly unpacks `pmessage` vs `message` event types
- That the session_id extraction from the channel key is correct
- That malformed session IDs are filtered before forwarding
- That the `LessonPackage` cache write happens after successful deserialization

### Root Cause E — Intervention event persistence (2 FAILED)

**Affected file:** `tests/test_intervention_event_persistence.py`

**Failing tests:**
```
FAILED tests/test_intervention_event_persistence.py::test_redis_miss_triggers_db_count_reconstruction
FAILED tests/test_intervention_event_persistence.py::test_redis_hit_skips_db_reconstruction
```

**Root cause:** The intervention count cache (Redis) has a read-miss path that should
fall back to reconstructing the count from the DB, and a read-hit path that should skip
the DB entirely. One or both paths have implementation bugs.

**Fix required:** Audit the intervention persistence module. The Redis key used for the
count cache must match between the write path and the read path. The DB reconstruction
query must be bounded (`.limit()` on `session_events` count).

---

## Integration Test Failures (Not Unit Tests)

### `tests/test_llm_provider_smoke.py` — 2 FAILED

**Failing tests:**
```
FAILED tests/test_llm_provider_smoke.py::test_complete_returns_text
FAILED tests/test_llm_provider_smoke.py::test_complete_structured_parses_pydantic
```

**Root cause:** These are **integration tests** that require a real `OPENAI_API_KEY`
environment variable. They fail with `openai.AuthenticationError` or similar when the
key is absent.

**This is expected behaviour in unit CI.** These tests should be marked
`@pytest.mark.integration` and excluded from the standard `pytest` run with
`-m "not integration"`. They should only run in a CI step that has real API credentials.

**Fix required:** Add `@pytest.mark.integration` to both tests and update the CI
workflow (`pytest -m "not integration"` for the standard run). Do NOT add a real API
key to CI secrets just to make these pass in the unit gate.

---

## Recommended Fix Order

### Dev 4 (unblock Dev 1's 66 ERRORs first)

1. **Fix auth router 204 body** — unblocks Dev 1's 66 ERRORs immediately
2. **Fix JWT 401 vs 403** — `test_alg_none_token_rejected` (security-critical, 500 crash)
3. **Fix fatigue Redis key** — 3 tutor graph tests
4. **Fix PubSub subscriber** — 3 lesson-ready tests
5. **Fix intervention persistence** — 2 tests

### Dev 1 (after Dev 4 unblocks the ERRORs)

1. **Fix `tts_node.py` state spread** (`test_node_return_shape`) — binding rule violation,
   HIGHEST PRIORITY; causes channel duplication on every retry
2. **Add `tinytag` to `pyproject.toml`** — unblocks all 22 `test_tts_node` tests
3. **Implement book endpoints** — `list_books`, `get_book`, `list_chapters`
4. **Complete content router** — upload flow, lesson GET/LIST
5. **Complete generate endpoint** — lesson generation trigger with all guards
6. **Add eval fixtures or skip test** — `test_extract_page_bounds`
7. **Implement eval runner** — `test_eval_runner`
8. **Mark smoke tests integration** — `test_llm_provider_smoke`

---

## Verification Commands

After Dev 4 fixes the auth router:
```bash
cd apps/api
python -m pytest tests/unit/test_admin_router.py tests/unit/test_content_router.py tests/unit/test_media_router.py -q 2>&1 | tail -3
# Expect: 0 errors (tests may still fail on unimplemented logic, but no ERRORs)
```

After Dev 1 fixes the TTS node spread:
```bash
python -m pytest tests/unit/test_node_return_shape.py -v
# Expect: PASSED
```

After Dev 1 adds `tinytag`:
```bash
python -m pytest tests/unit/test_tts_node.py -q 2>&1 | tail -3
# Expect: failures on logic bugs but no ModuleNotFoundError
```

Full Dev 3 suite (should show 0 failures in Dev 3 files):
```bash
python -m pytest tests/test_session_report_endpoint.py tests/test_s3_35_session_finalization.py tests/test_s3_42_ces_breakdown_accuracy.py tests/test_posthog_events.py -q
# Expect: 89 passed
```
