---
id: "S3-48"
title: "Lua atomic distraction cap check+increment and SET NX for cooldown/fatigue guards (D6)"
status: Draft
sprint: 3
story_points: 3
owner: Dev4
priority: P1
decisions: D6
depends_on: ["S3-35"]
branch: "sprint3/s3-48-lua-atomic-distraction-cap"
migration: "NO"
---

# Story S3-48 — Lua Atomic Distraction Cap Check+Increment and SET NX for Cooldown/Fatigue Guards (D6)

## Context

**Decision D6:** The two-step `EXISTS + GET` sequence in `_can_intervene_distraction`
(`apps/api/app/modules/tutor/state_machine/graph.py:120-126`) is a non-atomic check-then-act.
Two concurrent attention signals arriving within the same millisecond can both read
`count = 2 < max_distraction_per_session = 3`, both return True, both dispatch
`distraction_detected`, and both reach `intervening_node` — incrementing the distraction
counter to 4, violating the CLAUDE.md §10 guard "Max 3 distraction interventions per session".

**Current broken flow:**

```
Signal A: EXISTS(cooldown) → 0             Signal B: EXISTS(cooldown) → 0
Signal A: GET(count) → 2 (< 3)            Signal B: GET(count) → 2 (< 3)
Signal A: return True → dispatch            Signal B: return True → dispatch
Signal A: intervening_node INCR → 3        Signal B: intervening_node INCR → 4  ← cap exceeded
```

**D6 fix:** A Redis Lua script executes the entire check-then-act atomically (Redis is
single-threaded for Lua script evaluation). The script checks the cooldown key, checks the
distraction count, and — only if both guards pass — increments the count as part of the same
atomic operation. No race window exists between the read and the write.

Additionally, the writes in `intervening_node` for `tutor_cooldown` and `tutor_fatigue_fired`
use `SET NX` (write-only-if-absent) semantics, providing a second layer of protection:
if two concurrent calls somehow both enter `intervening_node`, only one can set the cooldown
and fatigue flag — the other's write is a no-op.

`process_attention_signal` (`apps/api/app/modules/tutor/service.py`) is updated to call
`_can_intervene_distraction` (the Lua guard) as a pre-check before dispatching
`distraction_detected` to the FSM, replacing the current cooldown-only `redis.exists` check.
This eliminates unnecessary FSM dispatches when the distraction cap or cooldown has been hit.

**Dependencies on S3-35:** S3-35 establishes `finalize_session` with the NX-based
`session:{session_id}:finalize_lock` pattern — the same idiomatic NX write used in this story
for cooldown and fatigue flags. S3-35 must be merged before this story proceeds.

## User Story

**As the system enforcing the tutor intervention rate limits,**
**I want** the distraction cap check and increment to execute as a single atomic Redis Lua
script,
**so that** concurrent attention signals cannot exceed the "max 3 distraction interventions per
session" guard defined in CLAUDE.md §10, regardless of how many worker replicas are running.

**As the system writing intervention flags to Redis,**
**I want** the cooldown and fatigue-fired keys to be written with SET NX semantics,
**so that** no concurrent execution of `intervening_node` can overwrite an existing cooldown
window or re-fire a fatigue flag that has already been set.

## Acceptance Criteria

### AC 1 — `_DISTRACTION_GUARD_LUA` constant exists in graph.py

A module-level string constant named `_DISTRACTION_GUARD_LUA` exists in
`apps/api/app/modules/tutor/state_machine/graph.py`.

The constant contains a valid Redis Lua script body. The script body satisfies all of the
following source assertions:
- Contains `redis.call('EXISTS', KEYS[1])` (or equivalent) — checks the cooldown key
- Contains `redis.call('GET', KEYS[2])` (or equivalent) — reads the distraction count
- Contains `redis.call('INCR', KEYS[2])` (or equivalent) — increments the count on success
- Contains `return 'ok'` — signals that the intervention slot was successfully reserved
- Contains `return 'cooldown'` or `return 'max_reached'` — signals that the guard blocked

**Exact assertion:**
```python
import inspect
from app.modules.tutor.state_machine import graph
assert hasattr(graph, "_DISTRACTION_GUARD_LUA")
lua = graph._DISTRACTION_GUARD_LUA
assert "EXISTS" in lua
assert "INCR" in lua
assert "'ok'" in lua or '"ok"' in lua
```

### AC 2 — `_can_intervene_distraction` calls Lua atomically (no separate EXISTS+GET)

The source of `_can_intervene_distraction` does NOT contain:
- A separate `redis.exists(cooldown_key)` call
- A separate `redis.get(count_key)` call

The source DOES contain a single `redis.eval(` call (or `await redis.eval(`).

The function accepts `(session_id: str, redis, settings)` — both `redis` and `settings` are
passed in (not fetched internally via `get_redis()` / `get_settings()`), making it testable
without patching module-level singletons.

**Exact assertions (source inspection):**
```python
src = inspect.getsource(_can_intervene_distraction)
assert "redis.exists" not in src      # no separate EXISTS
assert "redis.get" not in src         # no separate GET
assert "redis.eval" in src            # Lua eval is the single call
```

**Signature assertion:**
```python
import inspect as _i
sig = _i.signature(_can_intervene_distraction)
assert "redis" in sig.parameters
assert "settings" in sig.parameters
```

### AC 3 — Lua returns map to True/False correctly

Three unit tests with mocked `redis.eval`:

| `redis.eval` mock return | Expected `_can_intervene_distraction` return |
|--------------------------|---------------------------------------------|
| `b"ok"` | `True` |
| `b"cooldown"` | `False` |
| `b"max_reached"` | `False` |

The function must never raise when Lua returns any of these three values.

**Exact assertion example:**
```python
async def test_returns_true_on_ok():
    redis = AsyncMock()
    redis.eval = AsyncMock(return_value=b"ok")
    result = await _can_intervene_distraction("sess-001", redis, mock_settings)
    assert result is True
```

### AC 4 — `_can_intervene_distraction` fails closed on Redis error

When `redis.eval` raises any exception (e.g., `ConnectionError`, `TimeoutError`,
`redis.exceptions.ResponseError`), `_can_intervene_distraction` returns `False` and does
not propagate the exception.

A warning-level log is emitted with the session_id and the exception details.

**Exact assertion:**
```python
redis.eval = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
result = await _can_intervene_distraction("sess-001", redis, mock_settings)
assert result is False   # fail-closed: intervention blocked, not errored
```

### AC 5 — `process_attention_signal` pre-check calls `_can_intervene_distraction`

The source of `process_attention_signal` in `apps/api/app/modules/tutor/service.py` satisfies:
- Does NOT contain `await redis.exists(cooldown_key)` in the distraction dispatch block
- DOES call `_can_intervene_distraction` before the `dispatch_event("distraction_detected", ...)` call

The call passes `redis` and `settings` as arguments (matching the updated signature from AC 2).

**Exact assertion:**
```python
src = inspect.getsource(process_attention_signal)
assert "redis.exists(cooldown_key)" not in src   # old cooldown-only check removed
assert "_can_intervene_distraction" in src         # Lua guard present
```

### AC 6 — `process_attention_signal` does not dispatch when Lua blocks

When `_can_intervene_distraction` returns `False` (any reason — cooldown or max_reached), and
the tutor state is TEACHING, and the last two CES windows are below threshold:
- `dispatch_event` is NOT called with `"distraction_detected"`
- `CesResult.intervention_dispatched` is `False`

**Exact assertion (parametrized for both block reasons):**
```python
# With _can_intervene_distraction patched to return False:
result = await process_attention_signal("sess-001", low_ces_signal)
assert result.intervention_dispatched is False
# dispatch_event mock not called with "distraction_detected"
mock_dispatch.assert_not_called()
```

### AC 7 — `route_from_teaching` for `distraction_detected` no longer calls `_can_intervene_distraction`

The source of `route_from_teaching` does NOT call `_can_intervene_distraction` for the
`distraction_detected` branch. The guard has been moved to `process_attention_signal`; by the
time `distraction_detected` reaches the FSM router, the slot is already reserved.

**Exact assertion:**
```python
src = inspect.getsource(route_from_teaching)
# Specifically for the distraction_detected branch, no guard call exists
# (the function may still call _can_intervene_fatigue for fatigue_detected)
lines = src.splitlines()
distraction_block = [l for l in lines if "distraction_detected" in l or
                     (lines.index(l) > src.splitlines().index(
                         next(x for x in lines if "distraction_detected" in x)
                     ))]
# No _can_intervene_distraction call within 10 lines of "distraction_detected"
block = "\n".join(lines)
assert "_can_intervene_distraction" not in block
```

A simpler and sufficient assertion:
```python
src = inspect.getsource(route_from_teaching)
assert "_can_intervene_distraction" not in src
```

### AC 8 — `intervening_node` uses SET NX for the cooldown key

In `intervening_node`, the Redis write for `tutor_cooldown:{session_id}` uses `nx=True`:

```python
await redis.set(cooldown_key, "1", nx=True, ex=settings.intervention_cooldown_seconds)
```

**Exact assertion:**
```python
src = inspect.getsource(intervening_node)
assert "nx=True" in src   # SET NX is present
```

A concurrent second call to `intervening_node` for the same session (where the cooldown key
already exists) must receive `None` from the SET NX call and proceed without error.

### AC 9 — `intervening_node` uses SET NX for the fatigue_fired key

In `intervening_node`, the Redis write for `tutor_fatigue_fired:{session_id}` uses `nx=True`:

```python
await redis.set(f"tutor_fatigue_fired:{session_id}", "1", nx=True, ex=_STATE_TTL)
```

**Exact assertion:**
```python
src = inspect.getsource(intervening_node)
# Count occurrences of "nx=True" — must be at least 2 (one for cooldown, one for fatigue)
assert src.count("nx=True") >= 2
```

### AC 10 — Lua eval called with correct key and arg structure

When `_can_intervene_distraction("sess-xyz", redis, settings)` is called:
- `redis.eval` is called with `_DISTRACTION_GUARD_LUA` as the first argument
- The second argument (`numkeys`) is `2`
- `KEYS[1]` is `"tutor_cooldown:sess-xyz"`
- `KEYS[2]` is `"tutor_distraction_count:sess-xyz"`
- `ARGV[1]` is a string representation of `settings.max_distraction_per_session` (e.g. `"3"`)
- `ARGV[2]` is a string representation of the TTL for the count key (e.g. `"86400"`)

**Exact assertion:**
```python
redis.eval = AsyncMock(return_value=b"ok")
await _can_intervene_distraction("sess-xyz", redis, mock_settings)
call_args = redis.eval.call_args
assert call_args[0][0] == graph._DISTRACTION_GUARD_LUA
assert call_args[0][1] == 2
assert call_args[0][2] == "tutor_cooldown:sess-xyz"
assert call_args[0][3] == "tutor_distraction_count:sess-xyz"
assert call_args[0][4] == str(mock_settings.max_distraction_per_session)
```

### AC 11 — CI guard: no non-atomic two-step pattern in `_can_intervene_distraction`

A source-level CI guard in the test file asserts that the old non-atomic pattern is absent.
This guard prevents regression to the two-step EXISTS+GET.

**Exact assertion:**
```python
src = inspect.getsource(_can_intervene_distraction)
# The two non-atomic calls must be absent
assert "await redis.exists(" not in src
assert "await redis.get(" not in src
```

This test is named `test_no_non_atomic_two_step_in_can_intervene_distraction` and runs as
`@pytest.mark.unit`.

## Tasks / Subtasks

### Task 1 — Story file (story-first gate)
- [ ] 1.1 Create `docs/stories/S3-48-lua-atomic-distraction-cap-check-increme.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-48-lua-atomic-distraction-cap`
- [ ] 1.3 Push to remote before any implementation

### Task 2 — RED phase (failing tests)
- [ ] 2.1 Create `apps/api/tests/test_s3_48_lua_distraction_cap.py`
- [ ] 2.2 Write `test_distraction_guard_lua_constant_exists` (AC 1)
- [ ] 2.3 Write `test_lua_script_contains_exists_incr_ok` (AC 1)
- [ ] 2.4 Write `test_can_intervene_distraction_source_no_separate_exists_get` (AC 2, AC 11)
- [ ] 2.5 Write `test_can_intervene_distraction_signature_accepts_redis_settings` (AC 2)
- [ ] 2.6 Write `test_can_intervene_distraction_returns_true_on_lua_ok` (AC 3)
- [ ] 2.7 Write `test_can_intervene_distraction_returns_false_on_lua_cooldown` (AC 3)
- [ ] 2.8 Write `test_can_intervene_distraction_returns_false_on_lua_max_reached` (AC 3)
- [ ] 2.9 Write `test_can_intervene_distraction_fails_closed_on_redis_error` (AC 4)
- [ ] 2.10 Write `test_can_intervene_distraction_eval_called_with_correct_keys_and_args` (AC 10)
- [ ] 2.11 Write `test_process_attention_signal_source_uses_can_intervene_not_exists` (AC 5)
- [ ] 2.12 Write `test_process_attention_signal_no_dispatch_when_guard_returns_false` (AC 6)
- [ ] 2.13 Write `test_route_from_teaching_source_no_can_intervene_distraction_call` (AC 7)
- [ ] 2.14 Write `test_intervening_node_source_uses_nx_for_cooldown` (AC 8)
- [ ] 2.15 Write `test_intervening_node_source_uses_nx_for_fatigue` (AC 9)
- [ ] 2.16 Write `test_no_non_atomic_two_step_in_can_intervene_distraction` (AC 11)
- [ ] 2.17 Confirm all tests FAIL before implementation

### Task 3 — GREEN phase (implementation)

#### 3.1 — `graph.py`: Add `_DISTRACTION_GUARD_LUA` constant
```lua
-- KEYS[1] = tutor_cooldown:{session_id}
-- KEYS[2] = tutor_distraction_count:{session_id}
-- ARGV[1] = max_distraction_per_session (string)
-- ARGV[2] = TTL for count key in seconds (string)
local in_cooldown = redis.call('EXISTS', KEYS[1])
if in_cooldown == 1 then return 'cooldown' end
local count = tonumber(redis.call('GET', KEYS[2])) or 0
if count >= tonumber(ARGV[1]) then return 'max_reached' end
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
return 'ok'
```

#### 3.2 — `graph.py`: Rewrite `_can_intervene_distraction`
- Change signature to `(session_id: str, redis, settings) -> bool`
- Replace the EXISTS + GET calls with a single `redis.eval(_DISTRACTION_GUARD_LUA, 2, cooldown_key, count_key, str(settings.max_distraction_per_session), str(_STATE_TTL))`
- Return `True` iff result == `b"ok"` (or `"ok"`)
- Wrap in `try/except Exception` — return `False` and log WARNING on any Redis error

#### 3.3 — `graph.py`: Update `route_from_teaching` for `distraction_detected`
- Remove the call to `_can_intervene_distraction` from `route_from_teaching`
- The `distraction_detected` branch now just returns `"intervening"` directly
- The guard responsibility has moved to `process_attention_signal`'s pre-check (Task 3.4)

#### 3.4 — `service.py`: Update `process_attention_signal` pre-check
- Remove `in_cooldown = await redis.exists(cooldown_key)` from the distraction dispatch block
- Add `can_dispatch = await _can_intervene_distraction(session_id, redis, settings)` before the dispatch condition
- Update the condition: replace `not in_cooldown` with `can_dispatch`
- Import `_can_intervene_distraction` from `app.modules.tutor.state_machine.graph`

#### 3.5 — `graph.py`: Update `intervening_node` cooldown write to SET NX
- Change `await redis.set(cooldown_key, "1", ex=settings.intervention_cooldown_seconds)`
  to `await redis.set(cooldown_key, "1", nx=True, ex=settings.intervention_cooldown_seconds)`

#### 3.6 — `graph.py`: Update `intervening_node` fatigue write to SET NX
- Change `await redis.set(f"tutor_fatigue_fired:{session_id}", "1", ex=_STATE_TTL)`
  to `await redis.set(f"tutor_fatigue_fired:{session_id}", "1", nx=True, ex=_STATE_TTL)`

### Task 4 — REFACTOR + validation
- [ ] 4.1 `ruff check .` — zero new errors repo-wide
- [ ] 4.2 `ruff format --check` — zero format violations
- [ ] 4.3 Full Dev 3 + Dev 4 regression suite GREEN (`pytest -m unit`)
- [ ] 4.4 Confirm existing graph.py and service.py tests pass (no regressions)

### Task 5 — 6-agent adversarial review
- [ ] 5.1 Layer 1 — Story Quality
- [ ] 5.2 Layer 2 — Blind Hunter (Security)
- [ ] 5.3 Layer 3 — Test Coverage
- [ ] 5.4 Layer 4 — AC Completeness
- [ ] 5.5 Layer 5 — Process Integrity
- [ ] 5.6 Layer 6 — Scale & Load

### Task 6 — Commit + push
- [ ] 6.1 Final implementation commit on `sprint3/s3-48-lua-atomic-distraction-cap`
- [ ] 6.2 Push to remote
- [ ] 6.3 Update `docs/dev3-assessment-tracker.md`

## Scale & Load

### Q1 — What is ONE unit of work, and what is its range?

One unit of work is a single Redis Lua script evaluation triggered by one attention signal
window arriving in TEACHING state.

- **Min:** 0 Lua evaluations per session — session never enters TEACHING, or CES stays above
  threshold throughout, or history has fewer than 2 windows. No harm.
- **Typical:** 1–3 Lua evaluations per session (one per distraction event attempt). A typical
  30-minute lesson might trigger 0–2 distraction detection attempts; the Lua script evaluates
  once per attempt.
- **Largest measured:** The attention signal fires every ~5 seconds; if CES is below threshold
  for the entire session, `_can_intervene_distraction` is called on every window that meets the
  "2 consecutive below threshold" condition — roughly every other window — up to ~360 calls per
  60-minute session (720 windows / 2). After the third `'ok'` return, all subsequent calls return
  `'max_reached'` immediately (short-circuit after the EXISTS check passes and count >= max).
- **Beyond the bound:** After `max_distraction_per_session` (default 3) calls return `'ok'`, the
  Lua script returns `'max_reached'` on every subsequent call. The cost of that check is two Redis
  commands (EXISTS + GET): O(1), no growth.

One Lua script evaluation executes at most 4 Redis commands: EXISTS, GET, INCR, EXPIRE. All O(1).
No list scans, no set scans, no unbounded iterations.

### Q2 — Which budgets are FIXED while the input VARIES — and what happens past them?

| Budget | Value | Behaviour past the limit |
|--------|-------|--------------------------|
| `max_distraction_per_session` | 3 (env var `MAX_DISTRACTION_PER_SESSION`, default) | Lua returns `'max_reached'`; `_can_intervene_distraction` returns `False`; no dispatch. **Explicit block, not silent truncation.** |
| `intervention_cooldown_seconds` | 120 s (env var, default) | `tutor_cooldown:{session_id}` TTL expires → cooldown lifted. Key absence means cooldown cleared. |
| `_STATE_TTL` (count key TTL) | 86400 s (24 h) | After TTL, count key expires → next GET returns nil → count treated as 0. Session cannot span 24 h; this is correct behaviour. |
| Lua script commands per evaluation | 4 (EXISTS + GET + INCR + EXPIRE) | Fixed. Lua scripts in Redis execute atomically and cannot loop unboundedly. |

No silent exceedance: every fixed budget produces an explicit return code (`'cooldown'`,
`'max_reached'`) or a key expiry event that is directly observed on the next call.

### Q3 — What is the SCOPE of every limit?

| Limit | Scope | Notes |
|-------|-------|-------|
| `max_distraction_per_session` | Per deployment (env var) | Same max applies to all sessions on all replicas. The count key is per-session (`tutor_distraction_count:{session_id}`), so the cap is enforced per-session. |
| Cooldown window | Per session | `tutor_cooldown:{session_id}` key is session-scoped; two concurrent sessions have independent cooldowns. |
| Distraction count key | Per session | Session ID is a server-minted UUIDv4 — no two sessions share a key. |
| Fatigue flag | Per session | `tutor_fatigue_fired:{session_id}` is session-scoped. |
| Redis instance | Per deployment | Railway provides a single Redis. All FastAPI replicas share the same Redis — this is the reason the Lua atomicity is necessary. |

### Q4 — Which reads and writes are UNBOUNDED?

None introduced by this story.

- Lua script: EXISTS (O(1)) + GET (O(1)) + INCR (O(1)) + EXPIRE (O(1)). No scans.
- `SET NX` writes in `intervening_node`: O(1).
- No new Supabase queries.
- No new list reads or writes.
- Existing `lrange` calls in `process_attention_signal` are bounded by `_CES_HISTORY_MAX = 10`
  (established by S3-34, enforced by `ltrim`) — not changed by this story.

### Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?

`_STATE_TTL = 86400` (24 h) was set in `graph.py` when the state machine was first written.
It applies to `tutor_distraction_count:{session_id}` via the `EXPIRE` call in the Lua script.

Re-derivation: sessions cannot span 24 h (a lesson is 20–60 min). A count key surviving 24 h
would be orphaned from its session. Key expiry is correct behaviour; on next contact for the same
session_id (impossible in practice — session IDs are not reused), the count would reset to 0.
The inherited TTL is valid and re-confirmed.

`max_distraction_per_session = 3` is an env var (runtime-configurable). Its sizing rationale is
PRD §10 ("Max 3 distraction interventions per session"). Not changed by this story.

`intervention_cooldown_seconds = 120` is an env var. Not changed by this story.

### Q6 — Is every check-then-act sequence safe under CONCURRENT requests?

**Distraction cap check+increment:** Two concurrent requests arriving at `_can_intervene_distraction`
for the same session_id.

Without D6 (current code):
- Request A reads count=2, Request B reads count=2 — both see < 3 — both return True — both dispatch
  — `intervening_node` runs twice — count reaches 4 — cap exceeded.

With D6 (Lua script):
- Redis executes Lua scripts atomically (single-threaded Lua VM). Request A's Lua script runs to
  completion before Request B's starts.
- Request A: EXISTS cooldown → 0, GET count → 2, 2 < 3 → INCR (count=3) → return 'ok'
- Request B: EXISTS cooldown → 0, GET count → 3, 3 >= 3 → return 'max_reached'
- Result: exactly 1 dispatch. Cap enforced.

**Cooldown SET NX:** If two concurrent `intervening_node` calls somehow both enter the function
(e.g., FSM retry under partial failure), the first `SET NX` sets the cooldown key; the second
receives `None` (NX not acquired) and the key's original TTL is preserved. No double-reset of the
cooldown clock.

**Fatigue SET NX:** Same argument. First `SET NX` sets the fatigue flag; second is a no-op.
`_can_intervene_fatigue` (unchanged) reads this key via EXISTS — returns False (intervention
already fired) for the second concurrent call. The FSM therefore routes back to TEACHING.

No check-then-act gap exists for any of the three guards after this story.

## Security

### Authentication and session ownership

`_can_intervene_distraction` is called from `process_attention_signal`, which is invoked
exclusively from the WebSocket route handler (`apps/api/app/modules/tutor/router.py`). The
WebSocket connection is JWT-authenticated at connection time. The `session_id` flowing into
`process_attention_signal` is extracted from the validated WebSocket message and cross-checked
against the authenticated user's sessions. No attacker can supply an arbitrary `session_id`
to inflate or reset another user's distraction count.

### Redis key injection

The Redis Lua script receives key names as `KEYS[1]` and `KEYS[2]` arguments (not embedded in
the script string). The key names are constructed server-side from a server-minted UUIDv4
session_id. No user-controlled string is interpolated into the Lua script body or into the key
names. A client cannot cause the Lua script to address an arbitrary Redis key.

### Lua script execution constraints

The Lua script contains no loops, no blocking calls, no calls to external resources, and no
`redis.pcall` that would silently swallow Redis errors. Execution time is O(1) and bounded to
4 Redis commands. A malformed `count` value in the key (e.g., a non-numeric string left by a
bug) is handled by `tonumber(...) or 0` — defaults to 0 rather than erroring, which is
safe (treats the session as having 0 prior distractions, allowing interventions).

### No new attack surface

No new HTTP endpoints, no new database tables, no new migration files. Two existing functions
in `graph.py` are modified (implementation only, signatures change for `_can_intervene_distraction`).
One existing function in `service.py` is modified. No new data is persisted beyond what is
already written.

### Fail-closed on Redis error

If `redis.eval` raises during `_can_intervene_distraction`, the function returns `False`
(intervention blocked). This prevents interventions from firing when Redis is degraded —
preferring a missed intervention over a spurious one or an unhandled exception on the hot
attention signal path.

## Test Requirements

All tests live in `apps/api/tests/test_s3_48_lua_distraction_cap.py` and are
`@pytest.mark.unit` (no real Redis, no real DB).

| Test name | AC | What it asserts |
|-----------|-----|-----------------|
| `test_distraction_guard_lua_constant_exists` | AC 1 | `_DISTRACTION_GUARD_LUA` attribute exists on the graph module |
| `test_lua_script_contains_exists_incr_ok` | AC 1 | Lua source contains EXISTS, INCR, `'ok'` |
| `test_can_intervene_distraction_source_no_separate_exists_get` | AC 2, AC 11 | Source has no `redis.exists(` or `redis.get(` calls |
| `test_no_non_atomic_two_step_in_can_intervene_distraction` | AC 11 | Same as above — explicit CI guard name for the register |
| `test_can_intervene_distraction_signature_accepts_redis_settings` | AC 2 | `redis` and `settings` in function signature |
| `test_can_intervene_distraction_returns_true_on_lua_ok` | AC 3 | Mock eval→`b"ok"` → returns True |
| `test_can_intervene_distraction_returns_false_on_lua_cooldown` | AC 3 | Mock eval→`b"cooldown"` → returns False |
| `test_can_intervene_distraction_returns_false_on_lua_max_reached` | AC 3 | Mock eval→`b"max_reached"` → returns False |
| `test_can_intervene_distraction_fails_closed_on_redis_error` | AC 4 | Mock eval raises ConnectionError → returns False, no raise |
| `test_can_intervene_distraction_eval_called_with_correct_keys_and_args` | AC 10 | Verifies KEYS[1], KEYS[2], ARGV[1] content in eval call args |
| `test_process_attention_signal_source_uses_can_intervene_not_exists` | AC 5 | Source inspection: no `redis.exists(cooldown_key)` in dispatch block; `_can_intervene_distraction` present |
| `test_process_attention_signal_no_dispatch_when_guard_returns_false` | AC 6 | Patch `_can_intervene_distraction` → False; verify dispatch_event not called |
| `test_route_from_teaching_source_no_can_intervene_distraction_call` | AC 7 | Source of `route_from_teaching` has no `_can_intervene_distraction` |
| `test_intervening_node_source_uses_nx_for_cooldown` | AC 8 | Source of `intervening_node` contains `nx=True` |
| `test_intervening_node_source_uses_nx_for_fatigue` | AC 9 | Source of `intervening_node` contains at least 2 occurrences of `nx=True` |

**Regression tests** (no changes required, must remain GREEN):
- `apps/api/tests/` — full existing unit suite. In particular, any existing tests for
  `graph.py` guard functions and `process_attention_signal` must pass without modification.

## Decision References

| Decision | Description | Implementation in this story |
|----------|-------------|-------------------------------|
| D6 | Lua script replaces two-step EXISTS+GET in `_can_intervene_distraction`; pre-check in `process_attention_signal` before dispatch; SET NX for fatigue_fired and cooldown | Implemented as: `_DISTRACTION_GUARD_LUA` constant; rewritten `_can_intervene_distraction` using `redis.eval`; `process_attention_signal` calls `_can_intervene_distraction` before dispatch; `intervening_node` uses `nx=True` for cooldown and fatigue |

## Dependencies

- **S3-35** (session finalization, D11): Establishes the NX write pattern
  (`session:{session_id}:finalize_lock` with `nx=True`) that this story generalises to cooldown
  and fatigue flags. S3-35 must be merged to `main` before this story begins implementation.

## Migration

**NO** — No new Supabase tables, columns, or constraints. All changes are to Redis write patterns
and Python logic in `graph.py` and `service.py`. `supabase/migrations/` is unchanged.

## BMAD Process Gate

- [ ] Story file committed first (this file, before any implementation)
- [ ] Story commit pushed to `sprint3/s3-48-lua-atomic-distraction-cap` before any implementation
- [ ] RED tests written and failing before implementation
- [ ] GREEN implementation — all 15 tests pass
- [ ] REFACTOR — ruff 0 errors; no logic changes
- [ ] 6-agent adversarial code review completed
- [ ] `docs/dev3-assessment-tracker.md` updated

## Status

Draft
