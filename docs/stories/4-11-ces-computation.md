---
baseline_commit: "a4c6e18"
---

# Story 4-11: CES Computation In-Process (real §11 formula + `tutor_ces` persistence)

**Status:** done

---

## Story

As Dev 4,
I want `compute_ces()` to compute the real weighted Cognitive Engagement Score (PRD §11) from the five
attention signals — on the 0–100 scale Dev 3's assessment module already uses — and persist the result to
`tutor_ces:{session_id}`, fast enough that the in-process computation completes in < 5 ms,
so that the Sprint 3 `ces_computation` task is done and the intervention threshold (`CES < 50`) actually
works (today the stub returns `0.5`, which is `< 50` on every signal → it would fire constantly).

---

## Context (verified against source)

- `compute_ces(signal: NormalizedSignal) -> float` in `apps/api/app/modules/tutor/service.py:92` is a
  **stub returning `0.5`**. Its docstring says "Dev 3 replaces with the weighted formula from §11."
- **Dev 3 never shipped a unified `compute_ces`** — there is **no `apps/api/app/modules/assessment/ces.py`**.
  Dev 3 instead computes CES *contributions* inline in quiz/teach-back grading
  (`assessment/service.py:165`, `:312`) and documented a **scale contract** (`service.py:306-310`):
  > `ces_contribution` is on the **0–100 POINT** scale; `ces_weight_teachback` (0.25) = max 25 pts.
  > `CES = quiz_contrib + teachback_contrib + … (each 0–max_pts)`. Trigger threshold: `CES < 50`.
- The five weights are the **frozen shared contract** in `config.py:99-103`
  (`ces_weight_quiz=0.35, _teachback=0.25, _behavioral=0.20, _head_pose=0.12, _blink=0.08`; a validator
  enforces they sum to 1.0). `ces_threshold` default is `50.0` (`config.py:104`).
- Inputs are 0–1 fractions: `quiz_accuracy` / `teachback_score` may be `None` (not yet attempted / skipped);
  `behavioral_score`, `head_pose_score`, `blink_rate` are required floats (`NormalizedSignal`).
- §11 redistribution rule when `teachback_score is None`:
  `CES = quiz×0.467 + behavioral×0.267 + head_pose×0.160 + blink×0.107` (each weight = original ÷ 0.75).

### Design decisions (decisive — documented for review)

1. **Where it lives:** implement the real formula **in `tutor/service.py:compute_ces`** (where the stub
   already is). Do **NOT** create or edit anything under `assessment/` — that is Dev 3's module and the
   One-Discipline Rule forbids reaching into it. The weights come from `settings.ces_weight_*` (the shared
   frozen config), so this is not a cross-module DB access. *(If Dev 3 later publishes
   `assessment/ces.py:compute_ces`, this delegates to it — a follow-up, flagged below.)*
2. **Scale = 0–100.** `CES = (Σ signalᵢ × weightᵢ) × 100`, matching Dev 3's `ces_contribution` contract and
   making `ces_threshold = 50` correct. **This fixes the latent always-fire bug** (stub `0.5 < 50`).
3. **`None` handling = generalised §11 redistribution.** §11 documents only the teachback-`None` case.
   Generalise it: drop every `None` signal and **redistribute its weight proportionally across the present
   signals** (each present weight ÷ sum-of-present-weights). This reduces *exactly* to the §11 numbers when
   only teachback is `None` (present sum = 0.75 → ÷0.75). It also avoids a falsely-deflated CES early in a
   lesson when `quiz_accuracy` is `None` (no quiz yet) — otherwise CES would cap at 65 and false-trigger.
   Flag for Dev 3 (CES owner) to confirm the quiz-`None` extension. If **all** of quiz+teachback are `None`
   and somehow every signal is `None` (cannot happen — 3 are required), return `0.0` defensively.
4. **Persistence:** write `tutor_ces:{session_id}` = the CES (24 h TTL) in `process_attention_signal`,
   alongside the existing `ces_window` write. (`ces_window`/`ces_history` belong to `ces_redis_buffer`,
   already done — leave them.)
5. **Clamp** the result to `[0.0, 100.0]` (defensive against out-of-range input signals; Dev 3's parser is
   type-checked but not range-checked).

---

## Acceptance Criteria

- **AC 1:** `compute_ces(NormalizedSignal)` returns the §11 weighted score on the **0–100** scale using
  `settings.ces_weight_*`. With all five signals present: `(q·0.35 + t·0.25 + b·0.20 + h·0.12 + k·0.08)·100`.
- **AC 2:** When `teachback_score is None`, weights redistribute per §11 (÷0.75): the result equals
  `(q·0.4667 + b·0.2667 + h·0.16 + k·0.1067)·100` within rounding tolerance.
- **AC 3:** When `quiz_accuracy is None` (and/or teachback `None`), the same proportional redistribution
  applies across whatever signals are present (generalised rule); result stays in `[0, 100]`.
- **AC 4:** `process_attention_signal` writes `tutor_ces:{session_id}` = CES with a 24 h TTL (in addition
  to the existing `ces_window` write), and `CesResult.ces` carries the same value.
- **AC 5 (latency):** A benchmark test shows `compute_ces()` averages **< 5 ms** per call over many
  iterations (it is pure arithmetic — expect microseconds). The benchmark measures the **in-process
  computation**; Redis network I/O is excluded (environment-dependent), which is documented in the test.
- **AC 6:** Result clamped to `[0.0, 100.0]`.
- **AC 7:** Existing suite stays green — in particular `test_cesresult_fields` must no longer assert the
  stub `== 0.5`; the buffer-write tests already pin to the dynamic `_EXPECTED_CES = compute_ces(...)` symbol
  and need no value change.

---

## Tasks / Subtasks

- [ ] 1.1 Replace the `compute_ces` stub in `tutor/service.py` with the real formula: read weights from
  `get_settings()`, build a `{signal_value: weight}` map skipping `None` signals, redistribute by
  `present_weight / sum(present_weights)`, sum `value × redistributed_weight`, `× 100`, clamp `[0,100]`,
  return. Keep the `NormalizedSignal` signature. (Note: `compute_ces` is currently sync — it may call
  `get_settings()` directly; keep it sync to preserve the existing call site `ces = compute_ces(normalized)`.)
- [ ] 1.2 In `process_attention_signal`, add `await redis.set(f"tutor_ces:{session_id}", ces, ex=_CES_WINDOW_TTL)`
  next to the `ces_window` write.
- [ ] 1.3 Update `test_tutor_service.py::test_cesresult_fields` — drop `assert result.ces == 0.5`; keep the
  dynamic `assert result.ces == compute_ces(_parse_signal(_VALID_PAYLOAD))`.
- [ ] 1.4 New tests (Group G — CES formula): all-present correctness; teachback-`None` §11 numbers;
  quiz-`None` redistribution; both-`None` redistribution; clamp (signal > 1 → ≤ 100); `tutor_ces` write
  asserted in `process_attention_signal`; benchmark `< 5 ms` mean.
- [ ] 1.5 Run new tests + full regression.

---

## Dev Notes

### compute_ces (real formula)

```python
def compute_ces(signal: NormalizedSignal) -> float:
    """Weighted Cognitive Engagement Score on the 0–100 scale (PRD §11).

    Signals are 0–1 fractions; quiz_accuracy / teachback_score may be None. The weight of any None
    signal is redistributed proportionally across the present signals (generalises the §11 teachback
    rule: present-sum = 0.75 → each present weight ÷ 0.75). Result clamped to [0, 100].
    """
    from app.config import get_settings

    s = get_settings()
    # (value, weight) for every signal, dropping None ones.
    pairs = [
        (signal.quiz_accuracy, s.ces_weight_quiz),
        (signal.teachback_score, s.ces_weight_teachback),
        (signal.behavioral_score, s.ces_weight_behavioral),
        (signal.head_pose_score, s.ces_weight_head_pose),
        (signal.blink_rate, s.ces_weight_blink),
    ]
    present = [(v, w) for (v, w) in pairs if v is not None]
    weight_sum = sum(w for _, w in present)
    if weight_sum <= 0:
        return 0.0
    ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
    return max(0.0, min(100.0, ces))
```

### tutor_ces write (process_attention_signal)

```python
await redis.set(window_key, ces, ex=_CES_WINDOW_TTL)
await redis.set(f"tutor_ces:{session_id}", ces, ex=_CES_WINDOW_TTL)  # ces_computation (s3-3)
```

### Tests

- Patch `app.config.get_settings` to a real-weights `MagicMock` (quiz .35 / teachback .25 / behavioral .20
  / head_pose .12 / blink .08), or import the real `Settings()` defaults.
- **All present:** q=.8,t=.6,b=.9,h=.7,k=.3 → `(.8·.35+.6·.25+.9·.20+.7·.12+.3·.08)·100 = 71.8` (±1e-3).
- **teachback None:** q=.8,b=.9,h=.7,k=.3 → `(.8·.46667+.9·.26667+.7·.16+.3·.10667)·100 ≈ 75.733`.
- **quiz None too:** present = behavioral/head_pose/blink (sum .40) → each ÷ .40.
- **clamp:** behavioral=2.0 (bad input) → CES ≤ 100.
- **tutor_ces write:** assert `mock_redis.set.assert_any_call("tutor_ces:sess-1", <ces>, ex=86400)`.
- **benchmark:** `import time; N=2000; t0=time.perf_counter(); [compute_ces(sig) for _ in range(N)];`
  assert `(perf_counter()-t0)/N < 0.005`. Comment that this is in-process only (no Redis I/O), per AC5.

### Out of scope / flagged

- **Dev 3 reconciliation:** if/when Dev 3 publishes `assessment/ces.py:compute_ces`, delegate to it and
  delete this implementation (keep the `tutor_ces` persistence here). Confirm with Dev 3 (CES owner) that
  the **quiz-`None` redistribution** matches their intent — §11 only documents the teachback-`None` case.
- The `< 5 ms` AC's "including Redis write" wording: real Redis network latency is environment-dependent
  and untestable in CI; the benchmark measures the in-process computation (the task title's "in-process
  ~3–5 ms"). Documented in the test.

---

## Review outcome (adversarial — Blind Hunter + Edge Case Hunter, 2026-06-30)

**Blind Hunter: SHIP.** Hand-verified the formula (all-present = **71.8**, not the story's mistyped 70.4),
the exact §11 ÷0.75 redistribution (75.733), the 0–100 scale matching Dev 3's contract (and that it fixes
the latent always-fire stub bug, since `0.5 < 50`), the `weight_sum<=0` guard, and the `tutor_ces` key+TTL.
Grep confirmed no other consumer assumes a 0–1 CES (`tutor_ces` is write-only today; the only
`ces_threshold` comparison is 0–100 on both sides). Tests pin to the real formula; the clamp is genuinely
exercised.

**Edge Case Hunter: FIX-FIRST → fixed.**
- **[HIGH] Non-finite inputs.** `float("nan")`/`float("inf")` passed `_parse_signal` (type-check only);
  NaN propagated through `compute_ces` and clamped to **100 (maximally engaged)** — order-dependent on the
  `min/max` operands — silently suppressing interventions. **Fixed:** `_parse_signal` now rejects
  non-finite values (`math.isfinite`) in both the required and optional float paths. Tests:
  `test_parse_non_finite_required_raises` (nan/inf/-inf ×2), `test_parse_non_finite_optional_raises`.
  (±inf was already clamp-safe, but is now rejected at the boundary for consistency.)
- **[MED] Untested degrade branches.** Added `test_g4c_all_none_returns_zero` (the `weight_sum<=0` guard)
  and `test_g4b_clamps_to_zero` (lower-bound clamp on negative inputs).
- **[MED] Benchmark flakiness.** Added a warmup call before the timed loop so the first-call lazy import
  is excluded; measured margin is ~7 µs vs the 5 ms budget (~690×).
- **[LOW] confirmed no action:** `get_settings` is `@lru_cache`d (no per-call `Settings()` construction);
  the `tutor_ces` write shares the pre-existing (unguarded) `ces_window` failure surface — no NEW surface.

**Flagged — NOT changed:**
- **`[0,1]` range validation** of input signals belongs to the Completed `attention_ingestion` task (its AC
  asked for range rejection; `_parse_signal` only type-checks). The clamp defends the CES output range, so
  out-of-range inputs can't corrupt CES — but a true range-reject at the boundary is a follow-up for that task.
- **Zero-weight misconfiguration:** an env config setting all three always-present weights to 0 (while still
  summing to 1 via the optionals) could hit the `0.0` guard. Config-owner concern; the sum-to-1 validator
  could additionally require the three behavioral weights `> 0`.
- **Dev 3 reconciliation** of the quiz-`None` redistribution (extends §11) and the eventual move of the
  unified `compute_ces` into `assessment/ces.py` — as in the original story.
