---
status: done
baseline_commit: "af72477"
---

# Story 3-23 — CES v1 Formula Implementation

## Story

As **Dev 4 (WebSocket / tutor state machine)**, I want a pure Python `compute_ces()` function that accepts all 5 attention signals plus a `Settings` object and returns a 0–100 float, so that I can call it from the WebSocket handler on every `AttentionSignalMessage` without needing to understand CES formula internals or hold any weight constants locally.

## Acceptance Criteria

**AC 1 — Module created:** `apps/api/app/modules/assessment/ces.py` exists and is importable from anywhere in the `apps/api` package without errors.

**AC 2 — Public interface:** `ces.py` defines `__all__ = ["compute_ces"]` and exports exactly one public function. No other public symbols.

**AC 3 — Type signature (keyword-only):** The function signature is:
```python
def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float,
    head_pose: float,
    blink: float,
    settings: Settings,
) -> float:
```
All parameters are keyword-only (`*`). Returns `float` in range [0.0, 100.0]. Synchronous — no `async def`, no `await`.

**AC 4 — Weights from Settings, never hardcoded:** All 5 weight values are read from `settings.ces_weight_quiz`, `settings.ces_weight_teachback`, `settings.ces_weight_behavioral`, `settings.ces_weight_head_pose`, `settings.ces_weight_blink`. No numeric weight literal (e.g. `0.35`, `0.25`) appears anywhere in `ces.py`.

**AC 5 — Input clamping:** Each signal input is clamped to [0.0, 1.0] before weights are applied: values below 0.0 → 0.0; values above 1.0 → 1.0. Clamping is silent — no exception raised.

**AC 6 — Full 5-signal formula:** When both `quiz_accuracy` and `teachback_score` are not `None`:
```
raw = qa*w_quiz + tb*w_teachback + beh*w_behavioral + hp*w_head_pose + bl*w_blink
CES = round(raw * 100, 4)
```
Where each input is first clamped per AC 5.

**AC 7 — `teachback_score=None` redistribution (teach-back skipped):** When `teachback_score` is `None`, the teachback weight is redistributed proportionally across the remaining 4 signals:
```python
remaining = 1.0 - settings.ces_weight_teachback   # 0.75 at defaults
w_quiz_r  = settings.ces_weight_quiz       / remaining   # ≈ 0.4667
w_beh_r   = settings.ces_weight_behavioral / remaining   # ≈ 0.2667
w_head_r  = settings.ces_weight_head_pose  / remaining   # ≈ 0.1600
w_blink_r = settings.ces_weight_blink      / remaining   # ≈ 0.1067
raw = qa*w_quiz_r + beh*w_beh_r + hp*w_head_r + bl*w_blink_r
CES = round(raw * 100, 4)
```
`qa` uses `quiz_accuracy` clamped (or 0.0 if `quiz_accuracy` is also `None` — see AC 8). This is NOT a penalty: the redistributed weights still sum to 1.0, so a fully-engaged student still scores 100.

**AC 8 — `quiz_accuracy=None` handling (quiz not yet submitted):** `quiz_accuracy=None` means no quiz attempt has been recorded in the current window yet — it is a transient "no data" state. It is treated as `0.0` with its full weight retained (NOT redistributed). Redistribution only applies to `teachback_score=None` because a skipped teach-back is permanent for the segment, whereas a missing quiz_accuracy is temporary.

**AC 9 — Division-by-zero guard:** If `remaining_weight = 1.0 - settings.ces_weight_teachback` evaluates to `≤ 0` (degenerate config), `compute_ces()` returns `0.0` without raising. (This can only happen if `ces_weight_teachback = 1.0`, which `config.py`'s `@model_validator` prevents in practice — the guard is a safety net.)

**AC 10 — All-zeros → 0.0:** `compute_ces(quiz_accuracy=0.0, teachback_score=0.0, behavioral=0.0, head_pose=0.0, blink=0.0, settings=s)` → `0.0`.

**AC 11 — All-ones → 100.0 (full formula):** `compute_ces(quiz_accuracy=1.0, teachback_score=1.0, behavioral=1.0, head_pose=1.0, blink=1.0, settings=s)` → `100.0` (±0.001 floating-point tolerance).

**AC 12 — All-ones → 100.0 (teachback None):** `compute_ces(quiz_accuracy=1.0, teachback_score=None, behavioral=1.0, head_pose=1.0, blink=1.0, settings=s)` → `100.0`. Redistributed weights sum to 1.0 by construction, so all-ones still yields 100.0.

**AC 13 — Mid-value correctness (full formula):** With default weights and all signals at 0.5:
```
CES = 0.5 × (0.35+0.25+0.20+0.12+0.08) × 100 = 0.5 × 100 = 50.0
```
Test asserts `pytest.approx(50.0, abs=0.001)`.

**AC 14 — Partial-value correctness (teachback None):** With default weights, `quiz_accuracy=1.0`, `teachback_score=None`, `behavioral=0.5`, `head_pose=0.5`, `blink=0.5`:
```
remaining = 0.75
CES = (1.0×0.35/0.75 + 0.5×0.20/0.75 + 0.5×0.12/0.75 + 0.5×0.08/0.75) × 100
    = (0.4667 + 0.1333 + 0.0800 + 0.0533) × 100
    ≈ 73.33
```
Test asserts `pytest.approx(73.33, abs=0.1)`.

**AC 15 — Out-of-range inputs clamped, not rejected:** `compute_ces(quiz_accuracy=1.5, teachback_score=-0.3, behavioral=2.0, head_pose=0.5, blink=0.5, settings=s)` does not raise; `quiz_accuracy` is treated as 1.0, `teachback_score` as 0.0, `behavioral` as 1.0.

**AC 16 — Custom weight correctness:** With weights `quiz=0.6, teachback=0.0, behavioral=0.2, head_pose=0.1, blink=0.1` (sums to 1.0) and all signals at 1.0, `compute_ces` returns `100.0`. (Non-default weights work correctly.)

**AC 17 — No DB / no LLM / no network / no async:** `ces.py` imports only from Python stdlib and `app.config`. Zero imports of `supabase`, `openai`, `posthog`, `httpx`, `requests`, `asyncio`, `aiohttp`. Verified by grepping the file.

**AC 18 — Test file and count:** `apps/api/tests/test_ces.py` exists with ≥ 15 `@pytest.mark.unit` tests, all passing under `pytest -m unit`.

**AC 19 — No regressions:** Full `pytest -m unit` suite passes after ces.py and test_ces.py are added. Existing 345 Dev 3 tests remain green.

## Tasks / Subtasks

- [x] Task 1: Write RED failing tests in `apps/api/tests/test_ces.py` — ✓ 2026-07-03
  - [x] 1.1 Create test file with `_settings()` factory helper (provides mandatory Settings fields)
  - [x] 1.2 Write test for AC 10 — all-zeros → 0.0
  - [x] 1.3 Write test for AC 11 — all-ones → 100.0 (full formula)
  - [x] 1.4 Write test for AC 12 — all-ones → 100.0 (teachback None)
  - [x] 1.5 Write test for AC 13 — mid-values 0.5 → 50.0
  - [x] 1.6 Write test for AC 14 — partial values with teachback None → ≈73.33
  - [x] 1.7 Write test for AC 8 — quiz_accuracy=None treated as 0.0
  - [x] 1.8 Write test for AC 7 — teachback=None redistribution weights sum to 1.0
  - [x] 1.9 Write test for AC 15 — out-of-range inputs clamped
  - [x] 1.10 Write test for AC 9 — division-by-zero guard returns 0.0
  - [x] 1.11 Write test for AC 16 — custom non-default weights
  - [x] 1.12 Write test for AC 17 — ces.py has no forbidden imports (AST-based)
  - [x] 1.13 Write test for AC 3 — compute_ces is keyword-only (positional args raise TypeError)
  - [x] 1.14 Write test for AC 6 — specific weighted sum at non-trivial partial values
  - [x] 1.15 Write test for AC 2 — `__all__` contains only `"compute_ces"`
  - [x] 1.16 Run `pytest apps/api/tests/test_ces.py -m unit -v` → ALL 17 tests FAIL (RED verified) ✓

- [x] Task 2: Implement `apps/api/app/modules/assessment/ces.py` (GREEN phase) — ✓ 2026-07-03
  - [x] 2.1 Create file with module docstring explaining CES formula, scale, and Dev 4 integration
  - [x] 2.2 Implement `compute_ces()` with input clamping, full formula, and teachback-None redistribution
  - [x] 2.3 Add division-by-zero guard for `remaining_weight ≤ 0` edge case
  - [x] 2.4 Run `pytest apps/api/tests/test_ces.py -m unit -v` → 17/17 tests GREEN ✓

- [x] Task 3: REFACTOR and verify — ✓ 2026-07-03
  - [x] 3.1 No hardcoded weight literals confirmed by test_no_hardcoded_weight_literals_in_ces_py (AST check) ✓
  - [x] 3.2 No forbidden imports confirmed by test_ces_py_has_no_forbidden_imports (AST check) ✓
  - [x] 3.3 Full suite: 431 passing, 18 pre-existing Dev 4/1 failures (unchanged), 0 regressions ✓

## Dev Notes

### Module location and role

`ces.py` lives alongside `service.py` at `apps/api/app/modules/assessment/`. It is a **pure synchronous computation module** — no DB, no LLM, no network, no event loop. Dev 4 imports `compute_ces` directly from their WebSocket handler:

```python
from app.modules.assessment.ces import compute_ces

ces_score = compute_ces(
    quiz_accuracy=payload.quiz_accuracy,      # from AttentionSignalMessage (ws.ts)
    teachback_score=payload.teachback_score,  # null = student skipped teach-back
    behavioral=payload.behavioral_score,
    head_pose=payload.head_pose_score,
    blink=payload.blink_rate,
    settings=get_settings(),
)
# Dev 4 checks: ces_score < settings.ces_threshold (default 50.0) for 2 consecutive windows
```

### CES scale: 0-100 POINT scale (critical for Dev 4)

`compute_ces()` returns values on the **0-100 POINT scale** — consistent with the existing codebase:

- `service.py:276` `grade_quiz()`: `ces_contribution = round(quiz_accuracy * settings.ces_weight_quiz * 100, 4)` — max 35.0 pts
- `service.py:459` `grade_teachback()`: `ces_contribution = round((score/100) * settings.ces_weight_teachback * 100, 4)` — max 25.0 pts
- `service.py:628` `get_session_report()` `ces_breakdown` dict uses the same per-component point scale

Dev 4 compares the returned float directly against `settings.ces_threshold` (default 50.0 on the 0-100 scale). **Do NOT multiply by 100 again in the WebSocket handler.**

### config.py already has all CES env vars (lines 109–117)

No changes to `config.py` are needed:
```python
ces_weight_quiz:       float = Field(default=0.35, ge=0.0, le=1.0)
ces_weight_teachback:  float = Field(default=0.25, ge=0.0, le=1.0)
ces_weight_behavioral: float = Field(default=0.20, ge=0.0, le=1.0)
ces_weight_head_pose:  float = Field(default=0.12, ge=0.0, le=1.0)
ces_weight_blink:      float = Field(default=0.08, ge=0.0, le=1.0)
ces_threshold:         float = Field(default=50.0)
```

`config.py:119–133` has a `@model_validator` that enforces these 5 weights sum to 1.0 ± 0.001. `compute_ces()` can trust this invariant — no re-validation needed.

### Why `quiz_accuracy=None` is NOT redistributed (AC 8)

From `packages/shared/types/ws.ts` `AttentionSignalMessage`:
```typescript
quiz_accuracy: number | null;   // null = no quiz submitted yet in this 5s window
teachback_score: number | null; // null = student chose Skip (permanent for this segment)
```

- `quiz_accuracy=None` is **transient**: the next `AttentionSignalMessage` in 5s may have a real value once the student submits a quiz. Treating it as 0.0 is safe — it temporarily lowers CES, which errs on the side of offering help rather than missing a student in distress.
- `teachback_score=None` is **permanent** for the segment: once a student skips teach-back, that signal will never arrive. Keeping the 0.25 weight active would permanently cap CES at 75. Redistribution fixes this.

This asymmetry is spec'd in CLAUDE.md §11.

### Redistribution is computed from settings, not hardcoded

The divisor `remaining_weight = 1.0 - settings.ces_weight_teachback` is computed at call time. If an operator tunes `CES_WEIGHT_TEACHBACK` to 0.30, the redistribution automatically becomes `/0.70`. No code change needed.

### Settings factory for unit tests

`Settings` requires 9 mandatory fields even in tests. Use this factory to avoid boilerplate:

```python
from app.config import Settings

def _settings(
    quiz: float = 0.35,
    tb: float = 0.25,
    beh: float = 0.20,
    hp: float = 0.12,
    blink: float = 0.08,
) -> Settings:
    """Build a Settings instance with known CES weights for deterministic tests."""
    return Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
        heygen_api_key="x",
        langfuse_public_key="x",
        langfuse_secret_key="x",
        ces_weight_quiz=quiz,
        ces_weight_teachback=tb,
        ces_weight_behavioral=beh,
        ces_weight_head_pose=hp,
        ces_weight_blink=blink,
    )
```

Note: `Settings` does NOT use `@lru_cache` in tests (that is on `get_settings()`). Constructing multiple `Settings` instances in tests is fine.

### Reference implementation (for GREEN phase)

```python
from __future__ import annotations
from app.config import Settings

__all__ = ["compute_ces"]


def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float,
    head_pose: float,
    blink: float,
    settings: Settings,
) -> float:
    """Compute the Cognitive Engagement Score (CES) from 5 normalised signals.

    All inputs must be normalised to [0, 1] by the caller; out-of-range values
    are clamped silently. Returns a float on the 0-100 POINT scale.

    When teachback_score is None (student skipped teach-back), the 0.25 weight
    is redistributed proportionally across the remaining 4 signals so that a
    fully engaged student can still achieve CES = 100.

    Args:
        quiz_accuracy:   Fraction of quiz questions answered correctly (0–1), or
                         None if no quiz has been submitted yet (treated as 0.0).
        teachback_score: Normalised teach-back score (0–1), or None if the
                         student skipped teach-back for this segment.
        behavioral:      Normalised on-screen behavioural engagement score (0–1).
        head_pose:       Normalised head-pose attention score from MediaPipe (0–1).
        blink:           Normalised blink-rate score (0–1; higher = more alert).
        settings:        App settings carrying CES_WEIGHT_* env vars.

    Returns:
        CES score as a float in [0.0, 100.0] on the POINT scale.
        Dev 4 compares this against settings.ces_threshold (default 50.0).
    """
    # Clamp all signals to [0, 1]
    qa  = min(1.0, max(0.0, quiz_accuracy if quiz_accuracy is not None else 0.0))
    beh = min(1.0, max(0.0, behavioral))
    hp  = min(1.0, max(0.0, head_pose))
    bl  = min(1.0, max(0.0, blink))

    if teachback_score is None:
        # Redistribute teachback weight across the 4 remaining signals
        remaining = 1.0 - settings.ces_weight_teachback
        if remaining <= 0.0:
            return 0.0  # degenerate config guard (ces_weight_teachback == 1.0)
        raw = (
            qa  * (settings.ces_weight_quiz       / remaining)
            + beh * (settings.ces_weight_behavioral / remaining)
            + hp  * (settings.ces_weight_head_pose  / remaining)
            + bl  * (settings.ces_weight_blink      / remaining)
        )
    else:
        tb = min(1.0, max(0.0, teachback_score))
        raw = (
            qa  * settings.ces_weight_quiz
            + tb  * settings.ces_weight_teachback
            + beh * settings.ces_weight_behavioral
            + hp  * settings.ces_weight_head_pose
            + bl  * settings.ces_weight_blink
        )

    return round(raw * 100, 4)
```

### Files created / modified

| File | Action | Notes |
|------|--------|-------|
| `apps/api/app/modules/assessment/ces.py` | **NEW** | Pure computation — no DB, no LLM |
| `apps/api/tests/test_ces.py` | **NEW** | ≥15 unit tests, all `@pytest.mark.unit` |

No other files are modified. `service.py`, `router.py`, `config.py`, and all migrations remain unchanged.

### Dependency boundaries

| Who | Does what |
|-----|-----------|
| **Dev 3 (this story)** | Implements and tests `compute_ces()` — owns the formula |
| **Dev 4** | Calls `compute_ces()` from WebSocket handler; owns Redis storage and intervention trigger |
| **Dev 3 (Sprint 3 Task 2+)** | Will call `compute_ces()` for per-learner baseline and DNA fusion — ces.py must remain stable |

## Dev Agent Record

### Implementation Plan
RED → GREEN → REFACTOR cycle. Tests written first in `test_ces.py` (20 tests covering all 19 ACs). RED confirmed: all 17 initial tests failed on ModuleNotFoundError / FileNotFoundError. Implementation written as a pure synchronous function with input clamping, redistribution-on-teachback-None, and division-by-zero guard. GREEN: 17/17 pass. REFACTOR: AST-based tests verify no hardcoded literals and no forbidden imports. Post-review fixes: added output clamp (BLOCKER 1), teachback=0.0 vs None distinction test (BLOCKER 2), per-weight AC 7 verification, AC 5 head_pose/blink coverage. 20/20 pass.

### Debug Log
- RED phase: 17 failures confirmed before any implementation (all ModuleNotFoundError / FileNotFoundError)
- GREEN phase: 17/17 pass after writing ces.py (0.14s run time — pure computation, no IO)
- Code review phase: 5-agent adversarial review found 2 BLOCKERs + 3 IMPROVEMENTs
- Fix phase: 2 BLOCKERs resolved (output clamp + teachback=0.0 test); 3 tests added; 20/20 pass
- Full suite: 434 pass, 18 pre-existing Dev 4/1 failures (test_tutor_graph, test_tutor_service collection error; test_auth jwt warnings; test_websocket_session, test_lesson_ready_pubsub) — all unchanged

### Completion Notes
- Created `apps/api/app/modules/assessment/ces.py` — pure synchronous CES formula, no DB/LLM/network
- Created `apps/api/tests/test_ces.py` — 20 unit tests covering all ACs
- Key design decisions:
  - `teachback_score=None` redistributes weights; `quiz_accuracy=None` does not (treated as 0.0)
  - Division-by-zero guard for pathological `ces_weight_teachback=1.0` config
  - Output clamped to 100.0 — necessary because Settings allows weights to sum to 1.001
  - AST-based tests catch hardcoded literals and forbidden imports at test-time
  - All weight constants read from `settings` — swapping weights requires only env var change

### File List
- `apps/api/app/modules/assessment/ces.py` — NEW
- `apps/api/tests/test_ces.py` — NEW

### Change Log
- 2026-07-03: Story created — Sprint 3 Task 1 CES v1 formula (BMAD story-first gate, branch dev3-sprint3-task1)
- 2026-07-03: Implementation complete — ces.py + test_ces.py; 17/17 tests pass; 0 regressions
- 2026-07-03: Code review — 5-agent adversarial review; 2 BLOCKERs fixed; 20/20 tests pass

## Senior Developer Review (AI)

**Date:** 2026-07-03
**Branch:** dev3-sprint3-task1
**Reviewer:** 5-agent adversarial review (Story Quality · Blind Hunter · Test Coverage · AC Completeness · Process Integrity)
**Outcome:** APPROVED after fixes

### Findings

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Blind Hunter | **BLOCKER** | `raw` can exceed 1.0 in teachback-None redistribution when weight sum = 1.001 (within ±0.001 tolerance) → CES > 100.0 possible | Fixed: `return min(100.0, round(raw * 100, 4))` |
| 2 | Test Coverage | **BLOCKER** | No test distinguishes `teachback_score=0.0` from `teachback_score=None`. A `if not teachback_score:` bug passes all 17 tests silently. | Fixed: added `test_teachback_zero_uses_full_formula_not_redistribution` |
| 3 | Story Quality | IMPROVEMENT | `test_redistribution_weights_sum_to_one` was byte-for-byte duplicate of `test_all_ones_teachback_none_returns_100` | Fixed: replaced with `test_redistribution_weights_are_proportional` (asymmetric signals, per-weight verification) |
| 4 | AC Completeness | IMPROVEMENT | AC 5 clamping: `head_pose` and `blink` not tested with out-of-range values | Fixed: added `test_head_pose_and_blink_clamped_when_out_of_range` |
| 5 | Multiple | NITPICK | Test count header said "16" but 17 tests existed | Fixed: header updated to "20" |

### Action Items
- [x] BLOCKER 1: Add output clamp `min(100.0, ...)` to ces.py return statement
- [x] BLOCKER 2: Add test distinguishing teachback_score=0.0 vs None
- [x] IMPROVEMENT 3: Replace duplicate redistribution test with per-weight proportionality test
- [x] IMPROVEMENT 4: Extend AC 5 clamping coverage to head_pose and blink
- [x] NITPICK 5: Fix test count header
