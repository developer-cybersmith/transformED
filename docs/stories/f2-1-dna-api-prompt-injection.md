# Story F2-1 — Expose Learner DNA + Behaviour-Signal Summary as Internal Service Helper

**Sprint:** Bug Resolution (Feature Sprint 2)
**Priority:** Medium
**Owner:** Dev 3
**Status:** ready-for-dev
**Branch:** `feature2/f2-1-dna-api-prompt-injection`
**Story file committed before any implementation code** (CLAUDE.md Pre-Implementation Checklist)

---

## Story

As a service or pipeline node that builds an LLM system prompt,
I want to call a single async function that returns the student's current
Learner DNA (as descriptive labels, never raw floats) and session
behavioural signals (quiz accuracy, teachback average, intervention count)
as a typed dict,
so that I can inject rich, student-specific context into prompts without
duplicating Supabase / Redis read logic across callers.

---

## Background & Scope

This is a **pure service-layer addition** — no new HTTP route, no change to
the frozen 5-endpoint OpenAPI contract (CLAUDE.md Interface Contracts §1).
The helper lives in `apps/api/app/modules/assessment/service.py` alongside
the existing `get_learner_dna_data`, `seed_personalized_ces_threshold`, and
`get_session_report` functions.

### Why this is needed

`seed_personalized_ces_threshold` (S4-13) already proved the pattern: read
DNA from Redis cache → Supabase fallback → compute → store. Every future
story that needs DNA context for an LLM call (tutor Q&A personalisation,
intervention message personalisation, lesson planner context) would duplicate
this cache/fallback logic. F2-1 extracts it into one reusable helper.

### What "suitable for injection" means

The return dict is designed to be rendered into a compact prompt context
block. A companion formatting helper `format_dna_for_prompt` renders it as
a single string. Callers may use either the dict (for structured access) or
the string (for prompt insertion).

### IDOR scope note

All session signal queries filter by `session_id` only. This is sufficient
because `quiz_attempts`, `teachback_attempts`, and `session_events` all have
`session_id` as a foreign key to `sessions`, and `sessions` has `user_id`
with RLS. The queries do not add a redundant `user_id` filter — this matches
the existing `get_session_report` pattern.

---

## Acceptance Criteria

**AC1 — Function signature exists**
`async def get_dna_prompt_context(*, user_id: str, session_id: str | None, supabase: Client, redis: Any, settings: Settings) -> dict[str, Any]`
exists in `apps/api/app/modules/assessment/service.py`.

**AC2 — Return schema is exact**
The returned dict contains exactly these top-level keys:
- `dna_labels`: `dict[str, str]` — descriptive labels for each of the 9 DNA
  dimensions (uses existing `_score_to_label`). Keys: `pattern_recognition`,
  `logical_deduction`, `processing_speed`, `frustration_tolerance`,
  `persistence`, `help_seeking`, `goal_orientation`, `curiosity_index`,
  `study_independence`. If no DNA row exists the dict is `{}`.
- `badge_labels`: `list[str]` — from the DNA row; `[]` if no row.
- `profile_snippet`: `str | None` — first 200 chars of `profile_text` with
  `"…"` appended if truncated; `None` if no `profile_text`.
- `session_count`: `int` — from the DNA row; `0` if no row.
- `reassessment_due`: `bool` — from `user:{user_id}:reassessment_due` Redis
  key (same check as `get_learner_dna_data`); `False` on Redis failure.
- `session_signals`: `dict | None` — see AC6/AC7; `None` when `session_id`
  is `None`.

**AC3 — Redis cache hit: dimension values from Redis, metadata always from Supabase**
When `user:{user_id}:dna` exists in Redis (JSON blob with all 9 numeric
dimension values), the function reads the 9 numeric dimension values from
the cache blob. However, a Supabase query is STILL made on the cache-hit
path, selecting only `_METADATA_SELECT = "badge_labels, profile_text,
session_count"` (not the 9 dimension columns). This ensures `badge_labels`,
`profile_text`, and `session_count` always reflect the current database row,
even on a cache hit. On a Redis cache miss, a single Supabase query fetches
all 9 dimension columns AND the metadata columns (`_DNA_SELECT`). The cache
blob shape is the same as written by `dna_fusion.py` (9 numeric keys only —
metadata fields are never in the Redis blob).

**AC4 — Redis miss falls back to Supabase**
When the Redis DNA cache is absent or unparseable, the function queries
`supabase.table("learner_dna")` selecting all 9 dimension columns plus
`badge_labels`, `profile_text`, `session_count` with `.maybe_single()`.
Dimension values are then converted to labels via `_score_to_label`.

**AC5 — No DNA anywhere returns a graceful empty state**
When neither Redis nor Supabase has a `learner_dna` row for this user,
the function returns:
```python
{
    "dna_labels": {},
    "badge_labels": [],
    "profile_snippet": None,
    "session_count": 0,
    "reassessment_due": False,
    "session_signals": <value from session_id branch>,
}
```
It does NOT raise `HTTPException`. (Contrast: `get_learner_dna_data` raises
404 — this helper is non-fatal by design for use inside pipeline nodes.)

**AC6 — session_id=None returns session_signals=None without any DB query**
When `session_id` is `None`, `session_signals` is `None` and no
`quiz_attempts`, `teachback_attempts`, or `session_events` queries are made.

**AC7 — Session signals are bounded and correct**
When `session_id` is provided, the function queries:
- `quiz_attempts` filtered by `session_id`, `.limit(500)`, selects
  `is_correct` → `quiz_accuracy = correct_count / total_count * 100.0`
  (float 0-100, or `None` if no rows).
- `teachback_attempts` filtered by `session_id`, `.limit(100)`, selects
  `score` → `teachback_avg = mean(scores)` (float 0-100, or `None` if no rows).
- `session_events` filtered by `session_id` AND
  `event_type = "intervention_acknowledged"`, `.limit(1000)` → count of rows
  = `intervention_count` (int, 0 if no rows).

Result dict shape:
```python
{
    "quiz_accuracy": float | None,   # 0-100
    "teachback_avg": float | None,   # 0-100
    "intervention_count": int,       # always an int, minimum 0
    "signals_capped": bool,          # True if any query hit its .limit() boundary
}
```
When `signals_capped` is `True`, quiz_accuracy and/or teachback_avg are
computed from a capped row set and may be approximate. Callers building LLM
prompts should check this flag and add a caveat when True. The exception
fallback path always returns `signals_capped: False` (per SCALE-CONTRACT §2:
"explicitly surfaced degradation, visible to caller").

**AC8 — Non-fatal: all exceptions are swallowed**
Any exception during Redis read, Supabase DNA query, or Supabase session
signal query is caught, logged at `WARNING` with `user_id` sanitised (no
newlines), and the partial/empty result is returned. The function never
raises. Callers (LLM prompt builders) must never fail because of a missing
DNA context call.

**AC9 — No raw numeric dimension scores in any return value**
The `dna_labels` dict must contain only strings (descriptive labels from
`_score_to_label`). Numeric dimension values from Redis or Supabase must
never appear as values in the returned dict (at any nesting level in the
`dna_*` output keys). `session_signals` values (`quiz_accuracy`,
`teachback_avg`) are permitted as floats because they are behavioural
aggregates, not Learner DNA dimension scores.

**AC10 — `format_dna_for_prompt` helper exists and produces a usable string**
`def format_dna_for_prompt(context: dict[str, Any]) -> str` exists in
`service.py`. It is synchronous (no I/O). Returns a non-empty string
suitable for insertion into an LLM system prompt. Format (no float
literals):
```
[Student context] Badges: {badge_labels or "none"}. Profile: {snippet or "not set"}.
DNA ({n} dimension labels): {dim: label, ...}. Sessions completed: {n}.
{If session_signals} This session: quiz {quiz_accuracy:.0f}%, teachback {teachback_avg:.0f}%, interventions {n}.
```
When `dna_labels` is empty, the string says "No Learner DNA available yet."
The string contains no Python float literals — `quiz_accuracy` and
`teachback_avg` are rendered as `:.0f` (integer-style strings).

**AC11 — Existing guard tests pass (regression check)**
The following guard tests must pass after this story lands. This story does
NOT touch `ces.py`, but these are listed explicitly because they are
repo-wide architectural guards:
- `tests/test_ces.py::test_dunder_all_contains_only_compute_ces`
- `tests/test_ces.py::test_no_hardcoded_weight_literals_in_ces_py`
- `tests/unit/test_unbounded_queries.py` — all tests (new queries in
  `service.py` must carry `.limit()` or `.maybe_single()`)
- `tests/unit/test_node_return_shape.py` — not touched by this story

---

## Tasks / Subtasks

- [ ] T1 — Write failing unit tests (RED phase)
  - [ ] T1.1 AC1: import `get_dna_prompt_context` from service — fails if absent
  - [ ] T1.2 AC2: assert exact top-level keys in return dict
  - [ ] T1.3 AC3: Redis cache hit — assert supabase.table not called for DNA
  - [ ] T1.4 AC4: Redis cache miss — assert supabase.table("learner_dna") called with correct select
  - [ ] T1.5 AC5: no DNA anywhere — assert returns empty dna_labels dict without raising
  - [ ] T1.6 AC6: session_id=None — assert session_signals is None, no session DB calls
  - [ ] T1.7 AC7: session signals — assert quiz_accuracy/teachback_avg/intervention_count correct
  - [ ] T1.8 AC8: Redis exception swallowed — assert function returns without raising
  - [ ] T1.9 AC8: Supabase exception swallowed — assert function returns without raising
  - [ ] T1.10 AC9: no float dimension values in dna_labels — assert all values are str
  - [ ] T1.11 AC10: `format_dna_for_prompt` import and return type
  - [ ] T1.12 AC10: `format_dna_for_prompt` output contains no raw float dimension values
  - [ ] T1.13 Regression: existing guard test imports pass (import-level sanity check)

- [ ] T2 — Implement `get_dna_prompt_context` (GREEN phase)
  - [ ] T2.1 Redis cache read with `user:{user_id}:dna` key and JSON parse
  - [ ] T2.2 Supabase fallback: select all 9 dimensions + badge_labels + profile_text + session_count
  - [ ] T2.3 `_score_to_label` conversion of each dimension to descriptive label
  - [ ] T2.4 `profile_snippet` truncation at 200 chars + "…"
  - [ ] T2.5 `reassessment_due` Redis check (reuse existing pattern from `get_learner_dna_data`)
  - [ ] T2.6 Session signals branch: quiz, teachback, events queries with correct `.limit()` calls
  - [ ] T2.7 Exception handling wrapping all I/O with `try/except Exception`

- [ ] T3 — Implement `format_dna_for_prompt` (GREEN phase)
  - [ ] T3.1 Synchronous function, no I/O, renders context dict to compact string
  - [ ] T3.2 Empty `dna_labels` case: "No Learner DNA available yet."
  - [ ] T3.3 Session signals branch rendered as `: quiz N%, teachback N%, interventions N`

- [ ] T4 — Verify guard tests pass (REFACTOR phase)
  - [ ] T4.1 Run `pytest tests/test_ces.py -v` — all pass
  - [ ] T4.2 Run `pytest tests/unit/test_unbounded_queries.py -v` — all pass
  - [ ] T4.3 Run `pytest tests/unit/test_node_return_shape.py -v` — all pass

- [ ] T5 — Run full unit suite; verify no regressions

---

## Dev Notes

### Where to add the code

Both functions go in `apps/api/app/modules/assessment/service.py`, after the
`seed_personalized_ces_threshold` function (currently the last function in
the file, around line 1852).

### Redis DNA cache format

Written by `dna_fusion.py`. JSON blob with all 9 numeric dimension keys:
```json
{
  "pattern_recognition": 72.5,
  "logical_deduction": 68.0,
  "processing_speed": 55.0,
  "frustration_tolerance": 45.0,
  "persistence": 60.0,
  "help_seeking": 70.0,
  "goal_orientation": 62.0,
  "curiosity_index": 80.0,
  "study_independence": 58.0
}
```
The key is `user:{user_id}:dna`. TTL is 1h (set by `dna_fusion.py` — not
our concern to reset; we read it with `redis.get`).

### The 9 DNA dimension column names (canonical)

```python
_DNA_DIMS = (
    "pattern_recognition",
    "logical_deduction",
    "processing_speed",
    "frustration_tolerance",
    "persistence",
    "help_seeking",
    "goal_orientation",
    "curiosity_index",
    "study_independence",
)
```
Define this as a module-level constant in `service.py`. It is used in both
the Supabase SELECT string and the label-conversion loop.

### Existing helper to reuse

`_score_to_label(score: float) -> str` already exists in `service.py` at
line ~76. Use it for all 9 dimension conversions.

### Existing Redis reassessment_due pattern

The `get_learner_dna_data` function (line ~1669) has the exact Redis
`reassessment_due` read pattern with safe error handling. Copy it verbatim
into `get_dna_prompt_context`.

### Unbounded query guard

All new Supabase SELECT calls must satisfy `tests/unit/test_unbounded_queries.py`:
- `learner_dna` → `.maybe_single()` (UNIQUE user_id — always ≤1 row)
- `quiz_attempts` → `.limit(500)`
- `teachback_attempts` → `.limit(100)`
- `session_events` → `.limit(1000)`

### Test file location

New tests go in `apps/api/tests/unit/test_f2_1_dna_prompt_context.py`.
Mark all tests `@pytest.mark.unit`.

### Mock pattern to follow

Follow the same pattern as `tests/unit/test_s4_13_dna_ces_threshold.py`:
- `_make_settings()` factory returning `MagicMock` with relevant fields
- `AsyncMock` for redis, `MagicMock` for supabase chain
- Import the function inside the test body (not at module level) to catch
  `ImportError` in AC1 tests cleanly

### Do NOT touch

- `ces.py` — guard tests are strict equality on `__all__`
- `router.py` — frozen 5-endpoint contract
- `schemas.py` — no new public schema needed (internal dict, not HTTP response model)
- `dna_fusion.py` — not in scope

---

## Scale & Load

**Q1 — Unit of work and range**
One function call per prompt-build event. Typical callers: tutor service
building a system prompt for an intervention response (1–3 calls per session),
future lesson planner personalisation (1 call per chapter generation).
Range: 1 to ~20 calls per session; each call is independent (no shared state).

**Q2 — Fixed budgets vs variable input**
- Redis DNA read: O(1), always exactly one key regardless of dimension count.
- Supabase DNA fallback: `.maybe_single()` — PostgREST returns ≤1 row.
- `quiz_attempts`: `.limit(500)`. A typical session has ≤250 quiz rows
  (5 MCQs × 50 segments). At limit: rows beyond 500 are excluded from
  the accuracy computation, and `signals_capped=True` is set in the return
  dict so callers know the value is approximate (SCALE-CONTRACT §2:
  explicit surfaced degradation, not silent truncation).
- `teachback_attempts`: `.limit(100)`. Typical: ≤100 rows. At limit:
  `signals_capped=True` set — same explicit-surfacing pattern.
- `session_events`: `.limit(1000)`. Only `intervention_acknowledged` events
  are counted. Typical per session: <10. At limit: count may be slightly
  under-reported; `signals_capped=True` set.

**Q3 — Scope of limits**
All per session_id (bounded by session lifecycle) and per user_id (bounded
by UNIQUE constraint on learner_dna). Redis key is per-user.

**Q4 — Unbounded reads**
None. Every query carries `.limit()` or `.maybe_single()`. The unbounded
query CI guard (`test_unbounded_queries.py`) will catch any regression.

**Q5 — Inherited caps**
Redis DNA cache TTL 1h is inherited from `dna_fusion.py`. The 1h TTL is
appropriate because DNA updates happen at session end (sessions are
typically 15–45 min). No re-derivation needed for this story.

**Q6 — TOCTOU under concurrent requests**
Not applicable. This is a pure read function with no check-then-act
sequence. Multiple concurrent calls for the same user return the same data
independently; no shared mutable state is modified.

---

## Dev Agent Record

### Implementation Plan
_To be filled in by dev agent during implementation._

### Debug Log
_To be filled in by dev agent._

### Completion Notes
_To be filled in by dev agent._

### File List
_To be filled in by dev agent._

### Change Log
_To be filled in by dev agent._
