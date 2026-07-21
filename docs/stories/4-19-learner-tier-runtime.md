---
baseline_commit: "b390788"
status: review
---

# Story 4-19: Learner Mode — Session Runtime Reads Tier from Lesson Package

**Status:** in-progress
**Priority:** High
**Sprint:** Learner Mode (Feature Sprint)

---

## Story

As the tutor runtime,
I need to read the student's learner tier from the lesson package at session start and seed it into Redis,
so that downstream components (FSM, intervention engine) can adapt Q&A phase length and pacing to the student's tier.

---

## Context

- Three learner tiers: **T1** (10 min Q&A / 600 s), **T2** (5 min / 300 s), **T3** (2.5 min / 150 s).
- `lesson_package:{session_id}` is already cached in Redis by `core/pubsub.py` when the `lesson_ready` pub/sub event arrives. Story 4-19 reads from that cache — no new DB call needed.
- **CRITICAL BLOCKER — frozen contract:** `lesson_package.schema.json` and `packages/shared/types/lesson.ts` both have `LessonMetadata.additionalProperties = false` with no `learner_tier` field today. Adding `learner_tier` to `LessonMetadata` requires a **4-dev contract PR** before the lesson package cache will ever contain this field. This story must be submitted to trigger that PR conversation; implementation of AC1 is blocked until the PR lands. AC2–AC4 (Redis seeding from WS session-start payload) can proceed immediately without a contract change.
- `_init_session_state` in `apps/api/app/core/websocket.py:200` is the natural hook — it runs on every new WebSocket connection and already writes all per-session Redis keys.
- Tier info is ALSO sent by the client in the `session_start` control message (Story 4-21). Story 4-19 owns the lesson-package source of truth; Story 4-21 adds the WS fallback/override.

---

## Acceptance Criteria

- [ ] **AC1:** `lesson_package.schema.json` and `lesson.ts` both have `learner_tier: "T1" | "T2" | "T3"` as an **optional** field on `LessonMetadata`. *(Blocked on 4-dev contract PR — open the PR as part of this story's first commit.)*
- [x] **AC2:** On new WebSocket connect, `_init_session_state` reads `lesson_package:{session_id}` from Redis; if present and `metadata.learner_tier` is set, writes `session:{session_id}:learner_tier` (string, 24 h TTL).
- [x] **AC3:** `session:{session_id}:qa_phase_seconds` is written (as the string representation of an integer, 24 h TTL) using the mapping: T1 → `settings.learner_tier_t1_qa_seconds` (default 600), T2 → `settings.learner_tier_t2_qa_seconds` (default 300), T3 → `settings.learner_tier_t3_qa_seconds` (default 150). Unknown or missing tier values are rejected by the allowlist — neither key is written. The `qa_phase_seconds()` helper still returns the default (300) for unknown tiers for use by callers that already have a tier value.
- [x] **AC4:** If the lesson package cache is absent (lesson not yet generated), `_init_session_state` completes without error and writes neither key; a subsequent reconnect will retry the lookup and write the keys when the cache is populated.
- [x] **AC5:** All new settings (`learner_tier_t1_qa_seconds`, `learner_tier_t2_qa_seconds`, `learner_tier_t3_qa_seconds`, `learner_tier_default_qa_seconds`) are added to `config.py:Settings` as env-var-backed fields with the defaults above.
- [x] **AC6:** Unit tests cover: T1/T2/T3 mapping writes the correct `qa_phase_seconds` via pipeline; unknown tier (not in allowlist) → no keys written; non-dict metadata → no keys written; missing cache → no keys written; Redis failure → no crash.

---

## Implementation Notes

### 1. Contract PR (do this first, parallel to implementation)

Open a PR against `main` that adds `learner_tier` as **optional** to both frozen files:

```json
// lesson_package.schema.json — inside "LessonMetadata".properties
"learner_tier": {
  "type": "string",
  "enum": ["T1", "T2", "T3"]
}
// Do NOT add to "required" — field is optional; legacy packages without it must still validate.
```

```typescript
// lesson.ts — LessonMetadata interface
learner_tier?: 'T1' | 'T2' | 'T3';
```

Tag all 4 devs as reviewers. Do NOT merge until all 4 sign off.

### 2. New Settings fields (`config.py`)

Add to `Settings` after the existing intervention tuning block:

```python
# ── Learner Mode — Q&A phase lengths (seconds) ──────────────────────────
learner_tier_t1_qa_seconds: int = Field(default=600, description="Q&A phase for T1 (beginner) tier")
learner_tier_t2_qa_seconds: int = Field(default=300, description="Q&A phase for T2 (intermediate) tier")
learner_tier_t3_qa_seconds: int = Field(default=150, description="Q&A phase for T3 (advanced) tier")
learner_tier_default_qa_seconds: int = Field(default=300, description="Q&A phase when tier is unknown")
```

### 3. Helper in `service.py`

Add a pure function (no I/O, easily testable):

```python
def qa_phase_seconds(tier: str | None) -> int:
    from app.config import get_settings
    s = get_settings()
    return {
        "T1": s.learner_tier_t1_qa_seconds,
        "T2": s.learner_tier_t2_qa_seconds,
        "T3": s.learner_tier_t3_qa_seconds,
    }.get(tier or "", s.learner_tier_default_qa_seconds)
```

### 4. `_init_session_state` changes (`websocket.py:200`)

After writing the existing session keys, add a best-effort tier read (never raises):

```python
# Learner tier seeding — best-effort; never crash the handshake
try:
    raw_pkg = await redis.get(f"lesson_package:{session_id}")
    if raw_pkg:
        import json as _json
        from app.modules.tutor.service import qa_phase_seconds as _qa
        pkg = _json.loads(raw_pkg)
        tier = (pkg.get("metadata") or {}).get("learner_tier")
        if tier:
            await redis.set(f"session:{session_id}:learner_tier", tier, ex=86400)
            await redis.set(f"session:{session_id}:qa_phase_seconds", str(_qa(tier)), ex=86400)
            logger.info("WS session learner tier=%s qa_phase=%ss for %s", tier, _qa(tier), session_id)
except Exception:
    logger.warning("learner tier seeding failed for %s — continuing without tier", session_id)
```

### 5. Redis key additions

| Key | Type | Value | TTL |
|-----|------|-------|-----|
| `session:{session_id}:learner_tier` | str | `"T1"` \| `"T2"` \| `"T3"` | 24 h |
| `session:{session_id}:qa_phase_seconds` | str (int as string) | `"600"` \| `"300"` \| `"150"` | 24 h |

### 6. Files NOT to touch

- `packages/shared/lesson_package.schema.json` — only in the 4-dev contract PR
- `packages/shared/types/lesson.ts` — only in the 4-dev contract PR
- `apps/api/app/modules/tutor/state_machine/graph.py` — that's Story 4-20's territory
- `apps/api/app/core/pubsub.py` — already caches the lesson package correctly; no change needed

---

## Files to Change

| File | Change |
|------|--------|
| `apps/api/app/config.py` | Add 4 `learner_tier_*` settings fields |
| `apps/api/app/modules/tutor/service.py` | Add `qa_phase_seconds(tier)` helper |
| `apps/api/app/core/websocket.py` | `_init_session_state` — tier seeding block |
| `apps/api/tests/test_websocket_session.py` | New AC2–AC6 tests |
| `packages/shared/lesson_package.schema.json` | **4-dev PR only** — add optional `learner_tier` |
| `packages/shared/types/lesson.ts` | **4-dev PR only** — add optional `learner_tier` |

---

## Dev Agent Record

### Implementation Notes

- `qa_phase_seconds()` added to `service.py` as a pure function (no I/O) — fully testable without Redis.
- Tier seeding in `_init_session_state` uses a **separate** `try/except` block from the core session init, so a tier lookup failure never rolls back the IDLE state, distraction counter, or cooldown deletes.
- `get_redis()` is called twice (once in each block) — same singleton in production; both calls are mocked to the same mock in tests.
- `test_g9` uses `Settings.model_fields` introspection to verify defaults without requiring env vars.
- Pre-existing `test_auth.py` failures (PyJWT InsecureKeyLengthWarning, 6 tests) are unrelated to this story — confirmed pre-existing.

### Completion Notes

- AC1 deferred to 4-dev contract PR (lesson_package.schema.json + lesson.ts) — flagged as blocker, PR must be opened.
- AC2–AC6 fully implemented and tested: 9 new tests (G1–G9), 38/38 passing in `test_websocket_session.py`.
- Full suite of collectible tests: **105 passed, 0 regressions** from this story.

### File List

| File | Change |
|------|--------|
| `apps/api/app/config.py` | Added 4 `learner_tier_*_qa_seconds` settings fields |
| `apps/api/app/modules/tutor/service.py` | Added `qa_phase_seconds(tier)` pure helper |
| `apps/api/app/core/websocket.py` | `_init_session_state` — learner tier seeding block |
| `apps/api/tests/test_websocket_session.py` | 9 new Group G tests (AC2–AC6); added `import json` |

### Change Log

- 2026-07-21: Story 4-19 implemented — learner tier runtime seeding (AC2–AC6). AC1 blocked on 4-dev contract PR.
- 2026-07-21: Review patches applied — tier seeding extracted to `_seed_learner_tier()`; allowlist validation; pipeline atomicity; isinstance metadata guard; UUID route validation; reconnect race-condition fix; AC3/AC6 wording corrected. 42/42 tests green.

---

## Dependencies

- **Blocked on (partial):** 4-dev contract PR for `lesson_package.schema.json` + `lesson.ts` (AC1 only).
- **Unblocked:** AC2–AC6 can be implemented and tested before the contract PR lands using a synthetic Redis fixture that pre-seeds `lesson_package:{session_id}` with `metadata.learner_tier = "T2"`.
- **Enables:** Story 4-20 (`learner-qa-phase-length`) reads `session:{session_id}:qa_phase_seconds`.
- **Related:** Story 4-21 (`learner-ws-tier`) writes the same Redis key from the WS session-start payload as an override path.

---

## Senior Developer Review (AI)

**Review date:** 2026-07-21
**Layers:** Story Quality · Blind Hunter (Security) · Edge Case Hunter · AC Completeness · Process Integrity
**Outcome:** Changes Requested

### Review Follow-ups (AI)

#### Decision-needed

- [x] [Review][Decision] `session_id` used without format validation in Redis key construction — resolved: validated via `_SESSION_ID_RE` UUID regex at the `/ws/{session_id}` route boundary before `manager.connect()`. [Blind Hunter]

#### Patches

- [x] [Review][Patch] Tier value written to Redis without allowlist validation — fixed: `_VALID_TIERS = frozenset({"T1","T2","T3"})`; `if tier not in _VALID_TIERS: return` before pipeline write. [Blind Hunter] [`apps/api/app/core/websocket.py`]
- [x] [Review][Patch] Race condition — reconnect path skips tier seeding — fixed: extracted `_seed_learner_tier()` standalone coroutine; called from both fresh-init (`_init_session_state`) and reconnect branch (`_restore_or_init_session`). [Edge Case Hunter] [`apps/api/app/core/websocket.py`]
- [x] [Review][Patch] Broad `except Exception` can produce half-seeded state — fixed: both tier key writes go through `redis.pipeline(transaction=False)` for atomic dispatch. [Blind Hunter] [`apps/api/app/core/websocket.py`]
- [x] [Review][Patch] Non-dict truthy `metadata` causes silent AttributeError — fixed: `isinstance(metadata, dict)` check before `.get("learner_tier")`; non-dict → return early. [Edge Case Hunter] [`apps/api/app/core/websocket.py`]
- [x] [Review][Patch] `test_g4` missing assertion + behavior updated — `test_g4` rewritten: with allowlist, unknown tier "TX" → no keys written; test now asserts `mock_redis.pipeline.assert_not_called()`. [Story Quality] [`apps/api/tests/test_websocket_session.py`]
- [x] [Review][Patch] `_qa(tier)` called twice — fixed: `qa_secs = _qa(tier)` assigned once; used in both `pipe.set()` and `logger.info()`. [Edge Case Hunter + Process Integrity] [`apps/api/app/core/websocket.py`]
- [x] [Review][Patch] Story body Status field stale — fixed: body updated to `in-progress`. [Story Quality] [`docs/stories/4-19-learner-tier-runtime.md`]
- [x] [Review][Patch] AC3 wording corrected — updated to "string representation of integer" and notes that unknown/invalid tiers produce no Redis write. AC6 updated to match. [Story Quality + Edge Case Hunter]

#### Deferred

- [x] [Review][Defer] No test for `raw_pkg` returned as bytes — `json.loads()` accepts bytes in CPython; no bug. Consistent with existing codebase practice. [`apps/api/app/core/websocket.py:241`] — deferred, pre-existing pattern
- [x] [Review][Defer] No explicit test for malformed JSON payload — `json.JSONDecodeError` is correctly caught by `except Exception`; exception path already covered generically by test_g7. — deferred, pre-existing
- [x] [Review][Defer] `baseline_commit` updated inside impl commit — process irregularity; cannot be retroactively fixed. Note in PR description. — deferred, cannot fix retroactively
- [x] [Review][Defer] Tier+session_id logged at INFO level (DPDP consideration) — consistent with pre-existing `logger.info("WS session initialised: session=%s", session_id)` and `logger.info("WS connected: session=%s", ...)` throughout same file; broader PII-in-logs policy pre-dates this story. — deferred, pre-existing
- [x] [Review][Defer] `core/websocket.py` imports `modules/tutor/service` (module boundary) — pre-existing pattern used in three other dispatch helpers in the same file with documented rationale; not introduced by this change. — deferred, pre-existing
