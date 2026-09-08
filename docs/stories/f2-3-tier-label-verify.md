# Story F2-3 — Verify Learner Mode tier labels map to 15/30/45 min; relabel internally if needed

**Branch:** `feature2/f2-3-tier-label-verify`
**Owner:** Dev 3
**Sprint:** Bug Resolution Sprint (Feature Sprint 2)
**Created:** 2026-09-04

---

## Background

Learner Mode assigns each lesson one of three tiers (T1 / T2 / T3) that govern session depth and
Q&A phase length. The intended mapping is:

| Tier | Label       | Total session duration |
|------|-------------|------------------------|
| T1   | Full-Depth  | 45 min                 |
| T2   | Standard    | 30 min                 |
| T3   | Refresher   | 15 min                 |

`service.py` already exposes `_TIER_LABELS` with the correct semantic names. However:

1. No `_TIER_MINUTES` constant exists — the 15/30/45 minute values are implied by the labels but
   never written as code, so there is no machine-checkable assertion of this mapping.
2. `config.py`'s Q&A-phase field descriptions call T1 "beginner" and T3 "advanced" — the inverse
   of what the labels mean (T1 = Full-Depth = most thorough; T3 = Refresher = lightest). The
   Q&A second values (T1=600s, T2=300s, T3=150s) are correct and must not change; only the
   English descriptions are wrong.
3. There is no test asserting the constant mapping or the config descriptions.

**Scope:** Internal constants and field descriptions only. No API surface change (the user
confirmed `tier_minutes` should NOT be added to the `SessionReport` response).

---

## Acceptance Criteria

**AC1 — `_TIER_MINUTES` constant exists and maps correctly**
A module-level constant `_TIER_MINUTES: dict[str, int]` exists in
`apps/api/app/modules/assessment/service.py` with exactly:
```python
_TIER_MINUTES: dict[str, int] = {"T1": 45, "T2": 30, "T3": 15}
```
Keys match `_TIER_LABELS` exactly. No other value is allowed.

**AC2 — `_TIER_MINUTES` and `_TIER_LABELS` share the same key set**
`set(_TIER_MINUTES.keys()) == set(_TIER_LABELS.keys())` — a test asserts this at import time so
they can never drift independently.

**AC3 — Tier ordering is consistent**
`_TIER_MINUTES["T1"] > _TIER_MINUTES["T2"] > _TIER_MINUTES["T3"]` — T1 is always the longest,
T3 always the shortest. A test asserts this.

**AC4 — config.py Q&A-phase descriptions are corrected**
The three `learner_tier_t{n}_qa_seconds` field descriptions in `config.py` no longer say
"beginner", "intermediate", or "advanced". They now identify the tier by its label and minute
count:
- T1: `"Q&A phase duration in seconds for T1 (Full-Depth, 45-min) tier"`
- T2: `"Q&A phase duration in seconds for T2 (Standard, 30-min) tier"`
- T3: `"Q&A phase duration in seconds for T3 (Refresher, 15-min) tier"`

The `default` values (600 / 300 / 150) are unchanged.

**AC5 — Q&A seconds are consistent with tier depth**
`settings.learner_tier_t1_qa_seconds > settings.learner_tier_t2_qa_seconds > settings.learner_tier_t3_qa_seconds`
— a test asserts this ordering holds on a default `Settings()` instance, so a future env-var
tweak that inverts it is caught at test time.

**AC6 — No `tier_minutes` added to `SessionReport`**
The `SessionReport` Pydantic model in `router.py` does NOT gain a `tier_minutes` field. The
frozen assessment endpoint contract is unchanged. A test asserts the model's `model_fields` do
not include `tier_minutes`.

**AC7 — Guard tests for `service.py` pass unchanged**
`tests/unit/test_node_return_shape.py` and `tests/unit/test_unbounded_queries.py` pass with no
modifications.

**AC8 — No float literals or `__all__` changes in guarded modules**
`service.py` gains no new float literals (the `_TIER_MINUTES` values are `int`) and no `__all__`
change, so the `test_no_hardcoded_*` guard is not tripped.

---

## Out of Scope

- Adding `tier_minutes` to `SessionReport` or any other API response (confirmed out of scope)
- Changing Q&A default second values (600 / 300 / 150 are correct)
- Changing `_TIER_LABELS` values ("Full-Depth" / "Standard" / "Refresher" are correct)
- Any DB migration

---

## Scale & Load

**Q1 — Unit of work and range?**
One constant dict (`_TIER_MINUTES`, 3 keys) and three string field descriptions in `config.py`.
Min = typical = max = 3 tiers. Fixed forever at 3 — the PRD defines exactly three session depths
and there is no mechanism to add tiers at runtime.

**Q2 — Fixed budgets while input varies?**
None. This story adds a constant and fixes description strings; neither involves variable input,
token windows, or any LLM call. No silent truncation is possible.

**Q3 — Scope of every limit?**
Module-level constants: process-scoped, shared across all requests on an instance. No per-user or
per-request limit exists here. `config.py` field defaults are also process-scoped.

**Q4 — Unbounded reads or writes?**
None. No DB query, no Redis call, no LLM call. Pure constant definition and config description
edit.

**Q5 — Inherited caps re-derived?**
The Q&A second defaults (600 / 300 / 150) were set in a prior story. This story does not change
them; re-derivation not required. If a future story changes the per-tier minutes (15/30/45) it
MUST update `_TIER_MINUTES` and the config descriptions in the same commit.

**Q6 — Concurrent safety?**
N/A — immutable module-level constants are safe under any concurrency model.

---

## Test Plan

New test file: `apps/api/tests/unit/test_f2_3_tier_label_verify.py`

| # | Test | What it asserts |
|---|------|-----------------|
| 1 | `test_tier_minutes_values` | `_TIER_MINUTES == {"T1": 45, "T2": 30, "T3": 15}` exactly |
| 2 | `test_tier_minutes_keys_match_labels` | `set(_TIER_MINUTES) == set(_TIER_LABELS)` |
| 3 | `test_tier_ordering_t1_longest` | `T1 > T2 > T3` in `_TIER_MINUTES` |
| 4 | `test_config_t1_description_no_beginner` | T1 field description contains "Full-Depth" and "45" |
| 5 | `test_config_t2_description_no_intermediate` | T2 field description contains "Standard" and "30" |
| 6 | `test_config_t3_description_no_advanced` | T3 field description contains "Refresher" and "15" |
| 7 | `test_qa_seconds_ordering` | `t1_qa > t2_qa > t3_qa` on default `Settings()` |
| 8 | `test_session_report_no_tier_minutes_field` | `"tier_minutes" not in SessionReport.model_fields` |

Tests grew from 8 → 9 during the review (F2 patch added `test_tier_minutes_values_are_int_not_float`).
All 9 tests are RED before implementation and GREEN after.

---

## Review Findings

6-layer adversarial review run 2026-09-04 on branch `feature2/f2-3-tier-label-verify`. 2 patches applied; 0 deferred; 0 dismissed.

| ID | Sev | Layer | Finding | Action |
|----|-----|-------|---------|--------|
| F1 | Low | Edge Case Hunter | Unused `import pytest` in test file — ruff F401, blocks CI lint | Removed unused import |
| F2 | Low | AC Completeness | AC8 (`_TIER_MINUTES` values must be `int`) had no test assertion | Added `test_tier_minutes_values_are_int_not_float` |

**Scale & Load Hunter:** `[]` — no findings. Constant dict with 3 fixed keys, no variable input, no caps, no queries, no concurrency surface.

**Senior Developer Review:** All 6 layers ran and passed. Patches F1 and F2 applied and verified (9/9 tests GREEN). PR-ready.
