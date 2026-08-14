# Story 3-42: CES Breakdown Accuracy (D108, was D72)

## Story

**As a** student viewing my session report,  
**I want** the `ces_breakdown` to show actual behavioral, head_pose, and blink contributions,  
**so that** the per-component breakdown sums to the real CES score and gives meaningful feedback.

## Context

**Defect:** D108 (was D72) — `get_session_report` in `apps/api/app/modules/assessment/service.py` (lines 797–803) hardcodes `behavioral`, `head_pose`, and `blink` as `0.0` in `ces_breakdown`. The comment reads:

```python
# Sprint 2: behavioral/head_pose/blink contributions deferred to Phase 3
"behavioral": 0.0,
"head_pose": 0.0,
"blink": 0.0,
```

This means the reported `ces_breakdown` is always wrong for any session that had attention signals: its five values do not sum to `ces_score`, and `behavioral`, `head_pose`, and `blink` are always zero regardless of actual attention quality.

**Root cause:** `process_attention_signal` in `apps/api/app/modules/tutor/service.py` stores only the composite CES value in Redis (`session:{session_id}:ces_history`). The individual signal components (`behavioral_score`, `head_pose_score`, `blink_rate`) are never persisted, so `get_session_report` has nothing to read.

**Fix:** Two coordinated changes:
1. `tutor/service.py` — after each `process_attention_signal` call, also `lpush` the three individual signal components to separate Redis history lists (`session:{session_id}:behavioral_history`, etc.), trimmed and TTL'd identically to `ces_history`.
2. `assessment/service.py` — read those three history lists and compute weighted contributions.

**CES component scale:** The `ces_breakdown` dict uses the 0–100 POINT scale, matching `quiz_contribution` and `teachback_contribution`:
- `behavioral_contribution = avg_behavioral_score × settings.ces_weight_behavioral × 100`
- `head_pose_contribution = avg_head_pose_score × settings.ces_weight_head_pose × 100`
- `blink_contribution = avg_blink_rate × settings.ces_weight_blink × 100`

Where `avg_*` is the mean of values in the Redis history list (0–1 fractions, same units as `NormalizedSignal` fields).

**No signal history (empty list):** If no attention signals were recorded (the lists are empty or expired), contributions remain `0.0` — this is correct and intentional (not a fallback to the defective hardcoded value).

## Acceptance Criteria

### AC1 — Per-signal Redis history keys are populated by process_attention_signal
After `process_attention_signal` runs, Redis contains:
- `session:{session_id}:behavioral_history` — list of behavioral_score floats
- `session:{session_id}:head_pose_history` — list of head_pose_score floats
- `session:{session_id}:blink_history` — list of blink_rate floats

Each list: trimmed to `_CES_HISTORY_MAX` (10) entries, TTL = `_CES_WINDOW_TTL` (86400 s).

### AC2 — Per-signal histories use lpush + ltrim (newest-first, bounded)
The lpush/ltrim pattern mirrors `ces_history` exactly — index 0 is the most recent value; no more than `_CES_HISTORY_MAX` entries are kept.

### AC3 — get_session_report reads signal histories and computes weighted contributions
`ces_breakdown["behavioral"]`, `ces_breakdown["head_pose"]`, and `ces_breakdown["blink"]` are computed from the Redis history averages, not hardcoded to `0.0`. When the lists are non-empty, contributions equal `mean(values) × weight × 100`.

### AC4 — Empty signal history yields 0.0 contribution (not an error)
When Redis lists are empty or the keys do not exist (session with no attention signals, or TTL expired), contributions remain `0.0`. No exception is raised; no fallback error is logged.

### AC5 — Contributions use settings.ces_weight_* (not hardcoded floats)
`behavioral_contribution` uses `settings.ces_weight_behavioral`, `head_pose_contribution` uses `settings.ces_weight_head_pose`, `blink_contribution` uses `settings.ces_weight_blink`. These must be read from `get_settings()`.

### AC6 — Guard test: source inspection confirms no hardcoded 0.0 for behavioral/head_pose/blink
A CI-enforceable source scan confirms the pattern `"behavioral": 0.0` (literal zero) does NOT appear in the `get_session_report` implementation block.

### AC7 — DEFECT-REGISTER.md D108 (was D72) updated to FIXED with guard name

## Scale & Load

1. **Unit of work and range:** One `lpush` per signal component per attention window. Attention windows arrive every ~5 s while TEACHING; a typical 30-min lesson emits ~360 windows. Three extra keys per session = 3 × `_CES_HISTORY_MAX` = 30 entries max per session regardless of lesson length (ltrim bound).

2. **Fixed budget while input varies:** `ltrim` to `_CES_HISTORY_MAX = 10` entries per list — hard cap, no growth beyond 10 per component per session. TTL = 24 h. Storage: ~10 floats × 3 lists per session (bounded).

3. **Scope of limit:** Per session (Redis keys are session-scoped). Worker-count independent — Redis is the shared store, not process-local.

4. **Unbounded reads/writes:** None. `lrange(0, -1)` reads at most `_CES_HISTORY_MAX` entries. `get_session_report` reads exactly 3 lists of ≤10 entries each.

5. **Inherited caps re-derived:** `_CES_HISTORY_MAX = 10` matches the existing `ces_history` cap. Valid for the breakdown: 10 windows = 50 s of TEACHING data, sufficient for a representative average without unbounded growth.

6. **Check-then-act safety:** No check-then-act. `lpush` and `ltrim` are independent atomic operations, consistent with the existing `ces_history` pattern. Concurrent signals from the same session are additive (lpush) and trimmed to the same bound.

## Dev Notes

- Files to change:
  - `apps/api/app/modules/tutor/service.py` — `process_attention_signal` (after the existing `lpush(history_key, ces)` block)
  - `apps/api/app/modules/assessment/service.py` — `get_session_report` (Step 5, replace hardcoded 0.0)
- `get_session_report` receives `redis` via the `process_attention_signal` code path, but currently has NO `redis` parameter. The redis client must be injected — either as a new parameter or obtained via `get_redis()` inside the function.
- The `get_session_report` function signature change (adding `redis` param) must not break the existing router call site.
- `_CES_HISTORY_MAX` and `_CES_WINDOW_TTL` are defined in `tutor/service.py`. The new `lrange` reads in `assessment/service.py` must use the same constants — import them from `tutor/service.py` or duplicate the values with a comment citing the source.
- Do NOT change the `ces_breakdown` dict keys or their order.
- Do NOT change `quiz_contribution` or `teachback_contribution` — those are correct.

## BMAD Process Gate

- [x] Story file committed first
- [x] Story commit pushed to `sprint3/s3-42-ces-breakdown-accuracy` before any implementation
- [x] RED tests written and failing
- [x] GREEN implementation passes
- [x] REFACTOR (no logic changes)
- [x] DEFECT-REGISTER.md D108 (was D72) updated to FIXED + guard name

## Status

Done
