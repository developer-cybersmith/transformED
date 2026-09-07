---
id: "4-36"
title: "CI tests for dna_profile_quality_check.py + fix banned-term false positive"
status: "in-progress"
sprint: 4
story_points: 2
owner: Dev3
priority: P1
depends_on: ["4-33"]
---

# Story 4-36 — CI Tests for Learner DNA Profile Quality Checker

## Context

Story 4-33 delivered `scripts/dna_profile_quality_check.py` with 5 quality criteria
for `learner_dna.profile_text`. The Sprint 4 audit (2026-09-07) found that the script
has **zero CI tests** — no test file exists in the repo that exercises `check_profile()`
or `print_report()`.

Additionally, a logic bug was found during story creation:

> `BANNED_TERMS` includes `"clinical"` but the canonical `DPDP_DISCLAIMER` constant
> contains the phrase `"not a clinical assessment"`. Any profile that passes criterion 1
> (DPDP disclaimer present) will contain the word "clinical" and **always fail
> criterion 2** (No banned terms). The two criteria contradict each other for every
> compliant profile.

**Fix:** Strip the canonical disclaimer text from `profile_text` before scanning for
banned terms. The banned-term scan should only cover the *body* of the profile (the part
written by the LLM), not the mandatory disclaimer suffix.

## Story

**As a** Dev 3 maintaining the assessment quality gate,
**I want** `check_profile()` and `print_report()` covered by CI unit tests,
**and** the banned-term false-positive on `"clinical"` in the DPDP disclaimer fixed,
**so that** `pytest` enforces correct quality-checker behaviour in CI and a compliant
profile passes all 5 criteria.

## Acceptance Criteria

- [ ] **AC 1.** `apps/api/tests/test_s4_36_dna_quality_check.py` exists with ≥ 15
  `@pytest.mark.unit` tests, all passing in < 5 seconds with zero Supabase calls.

- [ ] **AC 2.** A fully valid profile (DPDP disclaimer present, no banned terms in body,
  no raw scores, length 100–500 chars, plain-English badge labels) → all 5 criteria
  return `"PASS"`.

- [ ] **AC 3.** Profile with no DPDP disclaimer → criterion `"DPDP disclaimer"` returns
  `"FAIL"`.

- [ ] **AC 4.** Profile with `"iq"` in body text (outside disclaimer) → criterion
  `"No banned terms"` returns `"FAIL"`.

- [ ] **AC 5.** Profile where `"clinical"` appears **only inside the DPDP disclaimer
  suffix** → criterion `"No banned terms"` returns `"PASS"` (disclaimer is excluded
  from the banned-term scan — **this is the bug fix AC**).

- [ ] **AC 6.** Profile with `"clinical"` in the body text (before the disclaimer) →
  criterion `"No banned terms"` returns `"FAIL"`.

- [ ] **AC 7.** Profile with banned term in a `badge_label` entry (e.g. `"iq"`) →
  criterion `"No banned terms"` returns `"FAIL"`.

- [ ] **AC 8.** Profile with raw score pattern `"87/100"` in body → criterion
  `"No raw scores"` returns `"WARN"`.

- [ ] **AC 9.** Profile with year `"2026"` in body (false-positive case) → criterion
  `"No raw scores"` returns `"PASS"` (year is NOT flagged).

- [ ] **AC 10.** Profile with `profile_text` shorter than 50 chars → criterion
  `"Length (50–800 chars)"` returns `"WARN"`.

- [ ] **AC 11.** Profile with `profile_text` longer than 800 chars → criterion
  `"Length (50–800 chars)"` returns `"WARN"`.

- [ ] **AC 12.** Profile with badge label `"IQ: 87"` → criterion
  `"Badge labels plain English"` returns `"FAIL"`.

- [ ] **AC 13.** Profile with `profile_text=None` → no `AttributeError`; criterion
  `"DPDP disclaimer"` returns `"FAIL"`; criterion `"Length (50–800 chars)"` returns
  `"WARN"` (0 chars).

- [ ] **AC 14.** `print_report()` called with at least one `"FAIL"` result → returns
  `True`.

- [ ] **AC 15.** `print_report()` called with all `"PASS"` results → returns `False`.

- [ ] **AC 16.** `ruff check` clean on `scripts/dna_profile_quality_check.py` (after
  bug-fix edit) and on the new test file.

- [ ] **AC 17.** Guard tests `tests/unit/test_unbounded_queries.py` and
  `tests/unit/test_node_return_shape.py` pass (the script's `.limit(500)` satisfies
  the unbounded-query guard; no LangGraph nodes touched).

## Scale & Load

**Q1 — Unit of work:** One call to `check_profile(row)` on one `learner_dna` row.
Range: `profile_text` is 0–10,000 chars (Supabase `text` column, no DB-level size cap;
practical: 100–600 chars based on 3-sentence generation prompt). `badge_labels` is a
JSON array of 0–9 string items (one per dimension).

**Q2 — Fixed budgets while input varies:** Pure Python regex + substring scan — O(n)
in `len(profile_text)` and `len(badge_labels)`. No LLM call, no network call, no
token window. Execution time < 1 ms per row regardless of text length. CI tests
complete in < 5 s for 15+ parameterised cases. No silent truncation risk.

**Q3 — Scope of every limit:** Tests are per-developer-machine / CI runner. The
main script's `.limit(500)` is per-Supabase project. Neither limit is shared across
instances.

**Q4 — Unbounded reads/writes:** Tests make zero DB calls — all in-memory.
Main script: `.limit(500)` on `learner_dna` SELECT — bounded. `# BOUNDED:` comment
already present in the script.

**Q5 — Inherited caps re-derived:** No inherited caps. The 500-row limit was set in
Story 4-33 for Sprint 4 (0 real students) and stated explicitly. If the student
population grows, the limit must be raised and re-derived — registered as D-nn
if not done before launch.

**Q6 — Check-then-act under concurrency:** Read-only script, read-only tests.
No TOCTOU concern.

## Tasks

- [ ] T1 — Story file (this file), committed, pushed (story-first gate)
- [ ] T2 — Fix `check_profile()` in `scripts/dna_profile_quality_check.py`:
  strip DPDP disclaimer from `profile_text` before banned-term scan (AC 5 bug fix)
- [ ] T3 — Write `apps/api/tests/test_s4_36_dna_quality_check.py` (RED → GREEN)
- [ ] T4 — Run all 15+ tests: confirm 0 failures
- [ ] T5 — Run guard tests: `tests/unit/test_unbounded_queries.py` + `test_node_return_shape.py`
- [ ] T6 — `ruff check` clean on both modified files
- [ ] T7 — Commit, push, open PR

## Dev Notes

### Import path for the test file

The script is at `scripts/dna_profile_quality_check.py` (repo root). Tests are at
`apps/api/tests/`. Add `scripts/` to `sys.path` at the top of the test file:

```python
import sys, os
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts")
))
from dna_profile_quality_check import check_profile, print_report, BANNED_TERMS
from app.modules.assessment.prompts import DPDP_DISCLAIMER
```

The script itself does `sys.path.insert(0, ".../apps/api")` on import — this is
harmless when run from `apps/api/tests/` since `apps/api` is already in scope.

### Bug fix — criterion 2 body scan

In `check_profile()`, change the banned-term scan to exclude the DPDP disclaimer:

```python
# Strip canonical disclaimer before scanning — avoids false positive on "clinical"
body_lower = profile_text.lower().replace(DPDP_DISCLAIMER.lower(), "")
found_banned = [t for t in BANNED_TERMS if t in body_lower]
```

The disclaimer is never placed in `badge_labels`, so the badge scan is unchanged.

### Valid test profile fixture

```python
_VALID_PROFILE = {
    "user_id": "test-user-001",
    "profile_text": (
        "You are a curious learner who builds understanding step by step. "
        "Your strength lies in connecting ideas across topics, which helps you "
        "retain information more effectively. "
        + DPDP_DISCLAIMER
    ),
    "badge_labels": ["Pattern Thinker", "Deep Diver"],
    "session_count": 1,
}
```

### DPDP_DISCLAIMER constant (live value as of 2026-09-07)

```
'This assessment reflects your personal learning preferences, not your
intelligence or capability. HIE Learner DNA is not a clinical assessment
and does not diagnose any learning or psychological condition.
— Pursuant to DPDP Act 2023.'
```

Source: `app.modules.assessment.prompts.DPDP_DISCLAIMER` — import it, never
hardcode it in test fixtures.

## Change Log

- 2026-09-07: Story created (BMAD story-first gate); bug in criterion 2 identified
  and documented as AC 5 fix target.
