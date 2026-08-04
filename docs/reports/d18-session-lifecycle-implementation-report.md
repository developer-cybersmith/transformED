# D18 — Session Lifecycle Endpoint: Implementation & Validation Report

**Story:** 2-35 — Mint sessions server-side (D18 — demo blocker)
**Branch:** `sprint2/s2-35-session-lifecycle`
**Date:** 2026-08-03
**Author:** Dev 3 review + lint fixes on Dev 1 implementation (option B)
**Status:** BMAD code review passed — ready to merge

---

## 1. Root Cause (confirmed by codebase analysis)

`sessions` had **zero INSERT writers** anywhere in the codebase. All 7 `table("sessions")` references in `apps/api` were `.select(...)`. The frontend at `player.machine.ts:142` generated a UUID with `crypto.randomUUID()`, which satisfied no foreign key constraints and was never persisted. `service.py:175` correctly rejected that invented UUID with HTTP 404. Result: **every quiz and teach-back submission 404'd for every student, always.**

Both test suites were green: Dev 3's fixtures seeded the row directly; Dev 2's tests mocked the POST. No test reconciled the two halves — `DEFECT-REGISTER.md` RC-1 in exact form.

The DB schema always intended server-side minting:
```sql
session_id  uuid  PRIMARY KEY DEFAULT gen_random_uuid()
user_id     uuid  NOT NULL REFERENCES public.users(id)
lesson_id   uuid  NOT NULL REFERENCES public.lessons(lesson_id)
started_at  timestamptz NOT NULL DEFAULT now()
```

---

## 2. What Changed

### New files

| File | Change |
|------|--------|
| `apps/api/tests/test_session_create_endpoint.py` | 10 new unit tests covering all ACs |
| `docs/stories/2-35-session-lifecycle-endpoint.md` | Story-first gate + completion notes |

### Modified files

| File | Change |
|------|--------|
| `apps/api/app/modules/assessment/schemas.py` | Added `SessionCreate`, `SessionCreated`; added both to `__all__` |
| `apps/api/app/modules/assessment/service.py` | Added `create_session()` — now the ONLY writer of `sessions`; W293/ANN401 lint fixes |
| `apps/api/app/modules/assessment/router.py` | Added `POST /sessions` endpoint; E402/S110 lint fixes |
| `apps/api/app/modules/assessment/dna_fusion.py` | ANN401 noqa suppression only |

---

## 3. Implementation Detail

### `POST /api/assessment/sessions`

**Endpoint** (`router.py`):
```python
@router.post("/sessions", response_model=SessionCreated, status_code=201)
async def create_session_endpoint(body: SessionCreate, current_user: CurrentUser):
    created = await create_session(
        lesson_id=body.lesson_id,
        user_id=current_user["sub"],  # JWT only — never from body
        supabase=get_supabase(),
    )
    return SessionCreated(**created)
```

**Service logic** (`service.py:create_session()`):
1. Reads `lessons` table for `lesson_id` and `user_id`
2. If row is missing **or** `user_id` mismatches — raises HTTP 404 (same response for both, per IDOR pattern)
3. INSERTs `{"user_id": ..., "lesson_id": ...}` — no `session_id`, no `started_at` (DB-generated)
4. Returns `{session_id, lesson_id, started_at}` from the DB-returned row

**Schemas** (`schemas.py`):
```python
class SessionCreate(BaseModel):
    lesson_id: str  # only accepted field

class SessionCreated(BaseModel):
    session_id: str
    lesson_id: str
    started_at: str | None = None
    # no user_id — security: never echo back JWT claims
```

---

## 4. Acceptance Criterion Verification

### AC-1 — `POST /api/assessment/sessions` creates a session and returns its id

**Evidence:**

_Test output:_
```
tests/test_session_create_endpoint.py::test_creates_a_session_and_returns_the_database_generated_id PASSED
tests/test_session_create_endpoint.py::test_user_id_comes_from_the_jwt_and_is_never_accepted_from_the_client PASSED
tests/test_session_create_endpoint.py::test_session_id_and_started_at_are_not_sent_to_the_database PASSED
```

_Code reference:_ `router.py:83-103` — endpoint returns 201 + `SessionCreated`. `user_id` is `current_user["sub"]`, never `body.user_id` (Pydantic ignores unknown fields). INSERT payload at `service.py:177-179` contains only `user_id` and `lesson_id`.

**PASS ✅**

---

### AC-2 — Lesson ownership enforced, absence indistinguishable from non-ownership

**Evidence:**

_Test output:_
```
tests/test_session_create_endpoint.py::test_a_lesson_owned_by_someone_else_returns_404_not_403 PASSED
tests/test_session_create_endpoint.py::test_a_missing_lesson_returns_the_same_404_as_an_unowned_one PASSED
```

_Code reference:_ `service.py:168-174`:
```python
if lesson_row is None or str(lesson_row.get("user_id", "")) != str(user_id):
    raise HTTPException(status_code=404, detail="Lesson not found")
```

Single branch for both cases. `test_a_missing_lesson_returns_the_same_404_as_an_unowned_one` asserts `missing.json() == unowned.json()` — body identity, not just status code.

**PASS ✅**

---

### AC-3 — Quiz submission succeeds end-to-end against a minted session

**Evidence:**

_Test output:_
```
tests/test_session_create_endpoint.py::test_a_minted_session_is_accepted_by_grade_quiz_ownership_check PASSED
```

_Test logic:_ Calls `create_session()`, captures `session_id`, passes it to `grade_quiz()` backed by a store that only contains rows the endpoint created. Asserts outcome == `"422"` (not `"404"`). 422 = reached answer validation = ownership check passed. Before D18 fix: this was `"404"` because the sessions row never existed.

**PASS ✅**

---

### AC-4 — Client-invented session id still rejected

**Evidence:**

_Test output:_
```
tests/test_session_create_endpoint.py::test_grade_quiz_still_rejects_a_session_id_that_was_never_minted PASSED
```

_Test logic:_ Calls `grade_quiz()` with a UUID that was never inserted. `maybe_single()` returns None → 404. The fix did not change the ownership check in `grade_quiz`; it only ensures a legitimate minted session passes it.

**PASS ✅**

---

### AC-5 — Re-learning produces a new session id

**Evidence:**

_Test output:_
```
tests/test_session_create_endpoint.py::test_the_same_user_starting_the_same_lesson_again_gets_a_new_session PASSED
```

_Test logic:_ Two calls to `_post()` share one in-memory `sessions` store. A reuse-if-exists implementation would find the first session via `select().eq(...)` and return the same ID — the assertion `first["session_id"] != second["session_id"]` would fail. `len(minted)==2` is the belt-and-suspenders guard. No UNIQUE constraint added (no migration touched).

**PASS ✅**

---

### AC-6 — Frontend contract documented

**Evidence:** Story completion notes (`docs/stories/2-35-session-lifecycle-endpoint.md`, "Still required before D18 can be called closed"):

> `player.machine.ts:142` must stop calling `crypto.randomUUID()` and use the returned id — that is Dev 2's change. Until it lands, the backend is correct and the product still 404s.

Dev 2 branch `origin/sprint2/s2-39-wire-real-session-id` already implements the frontend wiring. See Dev 2 Handoff section below.

**PASS ✅ (documented as hard prerequisite)**

---

### AC-7 — No regression

**Evidence:**

| Metric | Main | Branch | Delta |
|--------|------|--------|-------|
| Failing tests | 58 | 57 | **−1** (fixed auth assertion) |
| Passing tests | 1226 | 1227 | **+1** |
| Ruff errors (assessment module) | 7 | 0 | **−7** (E402, S110×2, W293×2, ANN401×2) |
| Mypy errors | 18 | 18 | 0 |
| New tests | — | 10 | +10 |

The 57 remaining failures are pre-existing: 19 × Dev 3 DNA growth tracking (not implemented), 3 × Dev 4 tutor state machine (not implemented). None introduced by this PR.

**PASS ✅**

---

## 5. BMAD Code Review Summary (5-agent layers)

| Layer | Verdict | Finding |
|-------|---------|---------|
| Story Quality | PASS | All 7 ACs satisfied; story-first gate confirmed on origin branch |
| Blind Hunter (Security) | PASS | No HIGH/MED findings; no IDOR leak, no client-field injection, no SQL injection |
| Test Coverage | PASS | All 10 behaviors covered; mutation testing confirmed no test-shaped gaps |
| AC Completeness | PASS | Every AC maps to ≥1 explicit assertion |
| Process Integrity | PASS | No LLM calls, no hardcoded models, lazy imports consistent with pattern |

**Applied patch:** `SessionCreate`/`SessionCreated` added to `schemas.py` `__all__` (LOW — cosmetic inconsistency).
**Deferred:** `lesson_id` has no `min_length=1` (pre-existing pattern across all string ID schemas).

---

## 6. Mutation Testing Results

9 mutants run on the implementation; 2 initial survivors, both fixed:

| Mutation | Result |
|---|---|
| D18 restored — no sessions writer | CAUGHT (7 tests) |
| Unowned lesson gets distinct 403 | CAUGHT |
| Ownership check removed | CAUGHT |
| Client-chosen `session_id` sent to DB | CAUGHT |
| Client-chosen `started_at` sent to DB | CAUGHT |
| Empty-insert guard removed | Survived → `test_an_insert_that_returns_no_row_is_a_500_not_a_crash` added |
| `user_id` trusted from body (no-op mutation) | Survived (no `user_id` field on `SessionCreate` — mutation was a no-op) |
| `user_id` trusted from body (faithful — field added too) | CAUGHT |
| Reuse-if-exists instead of insert | Survived → re-learning test rewritten to share one store, now fails 5 tests |

---

## 7. Dev 2 Handoff — AC-6 Frontend Wiring

**What the frontend must do:**

In `apps/web/src/stores/player.machine.ts`, the `LESSON_START` transition currently sets:
```typescript
// player.machine.ts:142 (approximate)
sessionId: crypto.randomUUID(),
```

This must change to:
1. Call `POST /api/assessment/sessions` with `{"lesson_id": lessonId}` (JWT auth header required)
2. On success (201): call `setSessionId(response.session_id)` — the `setSessionId` action already exists at line 185
3. On failure: surface an error state (the lesson cannot proceed without a valid session)

**Existing implementation:** Branch `origin/sprint2/s2-39-wire-real-session-id` already implements this. Dev 2 can merge or reference it directly.

**Why this matters:** Until this wiring is in place, the backend `POST /sessions` endpoint is correct but the product still 404s on every quiz/teach-back submission. D18 is not closed until this branch is merged.

---

## 8. Security Checklist

| Check | Status |
|-------|--------|
| `user_id` sourced from JWT only | ✅ |
| No client-injectable DB-generated fields | ✅ |
| Same 404 for missing and unowned lessons (no enumeration oracle) | ✅ |
| JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) | ✅ |
| No SQL injection (supabase-py parameterized queries) | ✅ |
| No LLM call in session creation path | ✅ |
| No migration changes (§16 four-dev gate not triggered) | ✅ |
| No `packages/shared/` changes (frozen contracts intact) | ✅ |
