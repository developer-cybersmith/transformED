# Story S3-47 — SessionReport formula_applied and signal_coverage fields: API disclosure of which CES formula variant was applied (D17)

**Status:** Draft
**Sprint:** 3
**Branch:** `sprint3/s3-47-ces-formula-disclosure`
**Decision reference:** D17
**Decisions covered:** D17
**Depends on:** S3-46 (ces_breakdown teachback redistribution — D2 must be merged first)
**Migration:** NO — no schema change; additive fields on existing `SessionReport` Pydantic model only

---

## Context

`GET /api/assessment/session/{session_id}/report` returns `ces_score` and `ces_breakdown` with no
machine-readable indication of:

1. Whether teachback-weight redistribution was applied (D2, delivered in S3-46).
2. How many signals contributed to the CES formula at report time.

After S3-46 is merged, `ces_breakdown` values for teachback-None sessions will be higher than for
teachback-present sessions (the 0.25 weight is redistributed proportionally). Without a
`formula_applied` discriminator, the frontend cannot determine which formula variant produced the
breakdown. Checking `ces_breakdown["teachback"] == 0.0` is an unreliable heuristic — a student who
skips teach-back AND scores exactly 0.0 on it (rare but valid) would be indistinguishable from a
student whose teach-back weight was redistributed.

`CLAUDE.md` binding rule 5: "Prose guidance does not hold." Documenting formula variants in the
OpenAPI description field is Option D in the decision record — explicitly rejected because it relies
on humans reading docstrings, which is the same pattern that let `structure_max_sections = 15`
survive multiple sprints of review.

**Decision record reference:** `docs/architecture/CES_DECISION_RECORD.md` §21 — D17 approves Option A:
add `formula_applied: Literal['full_5_signal', 'teachback_redistributed_4_signal']` and
`signal_coverage: int` as additive fields to `SessionReport`. Option B (expose raw effective
weights) was rejected as more verbose than needed. Option C (discrepancy warning only) was rejected
as non-actionable for UX copy. Option D (docstring only) was rejected by CLAUDE.md binding rule 5.

**Why this unblocks Dev 2:** The frontend needs to render contextually appropriate copy when
teach-back redistribution was applied — e.g., "Your teach-back score was not recorded; your quiz,
attention, and focus signals carry more weight this session." Without `formula_applied`, Dev 2 must
parse `ces_breakdown` values and guess the formula from component magnitudes, which breaks whenever
a student's raw signal happens to produce a value equal to the redistributed formula's output.

**Prerequisite:** D2 (S3-46) must be merged before this story is implemented. Adding
`formula_applied='teachback_redistributed_4_signal'` is misleading if `ces_breakdown` still uses
fixed nominal weights — the label would claim redistribution applied while the breakdown numbers
reflect fixed weights.

---

## Story

As a learner viewing my session report,
I want the API to disclose which CES formula variant was used to compute my breakdown
and how many signals contributed to my score,
so that the frontend can render a clear explanation of why my quiz, teach-back, attention, and
focus bars add up differently across sessions — and so my report is never silently misleading when
I skip teach-back.

---

## Acceptance Criteria

### AC 1 — formula_applied field present in SessionReport response

`GET /api/assessment/session/{id}/report` returns a JSON object that includes a `formula_applied`
string field. The field is present in every non-error response (200 OK), regardless of whether
teach-back was attempted.

Verified by: `assert "formula_applied" in report_dict`.

---

### AC 2 — formula_applied == 'full_5_signal' when teach-back was submitted

When the session has at least one row in `teachback_attempts` (i.e., `teachback_score is not None`
in the report computation), `formula_applied` is exactly the string `'full_5_signal'`.

Verified by: constructing a mock session with two `teachback_attempts` rows, calling
`get_session_report`, and asserting `report.formula_applied == 'full_5_signal'`.

---

### AC 3 — formula_applied == 'teachback_redistributed_4_signal' when teach-back was skipped

When the session has zero rows in `teachback_attempts` (i.e., `teachback_score is None` in the
report computation), `formula_applied` is exactly the string `'teachback_redistributed_4_signal'`.

Verified by: constructing a mock session with zero `teachback_attempts` rows, calling
`get_session_report`, and asserting `report.formula_applied == 'teachback_redistributed_4_signal'`.

---

### AC 4 — formula_applied type is Literal in the Pydantic model

`SessionReport.formula_applied` is typed as
`Literal['full_5_signal', 'teachback_redistributed_4_signal']` in `router.py`.

Verified by: `assert SessionReport.model_fields["formula_applied"].annotation is not str` — the
field annotation must be a `Literal`, not bare `str`. Alternatively, assert
`get_type_hints(SessionReport)["formula_applied"] == Literal['full_5_signal', 'teachback_redistributed_4_signal']`.

---

### AC 5 — signal_coverage field present in SessionReport response

`GET /api/assessment/session/{id}/report` returns a JSON object that includes a `signal_coverage`
integer field. The field is present in every non-error response (200 OK).

Verified by: `assert "signal_coverage" in report_dict`.

---

### AC 6 — signal_coverage == 5 when teach-back is present

When `teachback_score is not None` (at least one `teachback_attempts` row), `signal_coverage == 5`.

Rationale: All five CES signals (quiz, teachback, behavioral, head_pose, blink) are present in the
computation. Quiz and teachback have actual submission data. Behavioral/head_pose/blink are always
included in the formula (even if their contribution is 0.0 when attention monitoring is
unavailable). When teach-back is present the formula operates in the 5-signal mode.

Verified by: mock session with one `teachback_attempts` row → `assert report.signal_coverage == 5`.

---

### AC 7 — signal_coverage == 4 when teach-back is skipped

When `teachback_score is None` (zero `teachback_attempts` rows), `signal_coverage == 4`.

Rationale: Teach-back is the only signal that can be absent (None) in the formula computation.
The remaining four signals (quiz, behavioral, head_pose, blink) are always present in the formula
even when their data value is 0.0. signal_coverage reflects the number of signals entering the
formula, not the number of signals with non-zero data.

Verified by: mock session with zero `teachback_attempts` rows → `assert report.signal_coverage == 4`.

---

### AC 8 — signal_coverage type is int in the Pydantic model

`SessionReport.signal_coverage` is typed as `int` (not `float`, not `str`).

Verified by: `assert get_type_hints(SessionReport)["signal_coverage"] is int`.

---

### AC 9 — signal_coverage range is enforced [0, 5]

The implementation guarantees `0 <= signal_coverage <= 5`. A unit test constructs edge-case inputs
(all signals absent, all signals present) and asserts signal_coverage stays within bounds.

Verified by: `assert 0 <= report.signal_coverage <= 5` on both edge cases.

---

### AC 10 — formula_applied and signal_coverage are consistent

In every test scenario, the relationship `signal_coverage == 5` iff
`formula_applied == 'full_5_signal'` must hold. These two fields are not independent — they must
agree on the formula variant.

Verified by: parametrize over (teachback_present=True, teachback_present=False) and assert both
fields are consistent in both cases.

---

### AC 11 — formula_applied appears in the OpenAPI spec

Running `python apps/api/scripts/export_openapi.py` and parsing the resulting spec confirms that
the schema for `GET /api/assessment/session/{session_id}/report` includes `formula_applied` in its
response properties.

Verified by: `assert "formula_applied" in openapi_spec["components"]["schemas"]["SessionReport"]["properties"]`.

---

### AC 12 — signal_coverage appears in the OpenAPI spec

Same as AC 11 but for `signal_coverage`.

Verified by: `assert "signal_coverage" in openapi_spec["components"]["schemas"]["SessionReport"]["properties"]`.

---

### AC 13 — Additive only: no existing SessionReport field is changed

The addition of `formula_applied` and `signal_coverage` must not alter any existing field name,
type, or default. The test suite for existing session report fields (from Stories 3-19, 3-29,
3-30) must remain green without modification.

Verified by: run the full `pytest -m unit` suite and assert exit code 0.

---

### AC 14 — No migration, no Redis change, no LLM call

The implementation touches only:
- `apps/api/app/modules/assessment/router.py` — add two fields to `SessionReport`
- `apps/api/app/modules/assessment/service.py` — compute and populate those fields in
  `get_session_report`

No migration file is created. No Redis key is read or written. No LLM provider is called.

Verified by: CI passes with no new migration files and `git diff --name-only` shows only the two
Python files above (plus the test file).

---

## Tasks / Subtasks

- [ ] **T1** — Add `formula_applied: Literal['full_5_signal', 'teachback_redistributed_4_signal']`
  to `SessionReport` in `apps/api/app/modules/assessment/router.py`. Place it after
  `learner_dna_snapshot` (last existing field) to preserve stable field ordering. Import `Literal`
  from `typing` (already available via `from __future__ import annotations`; add to the runtime
  import block).

- [ ] **T2** — Add `signal_coverage: int` to `SessionReport` in the same file, immediately after
  `formula_applied`.

- [ ] **T3** — In `apps/api/app/modules/assessment/service.py:get_session_report`, after step 3
  (teachback stats), compute:
  ```python
  formula_applied = (
      "teachback_redistributed_4_signal" if teachback_score is None else "full_5_signal"
  )
  signal_coverage = 4 if teachback_score is None else 5
  ```
  Both variables must be computed BEFORE the `SessionReport(...)` constructor call at the end
  of `get_session_report` so they are always populated.

- [ ] **T4** — Pass `formula_applied=formula_applied` and `signal_coverage=signal_coverage` to the
  `SessionReport(...)` constructor at the end of `get_session_report`.

- [ ] **T5** — Write unit tests in
  `apps/api/tests/assessment/test_s3_47_formula_applied_signal_coverage.py`:
  - `test_formula_applied_full_5_signal_when_teachback_present`
  - `test_formula_applied_teachback_redistributed_when_teachback_absent`
  - `test_signal_coverage_5_when_teachback_present`
  - `test_signal_coverage_4_when_teachback_absent`
  - `test_signal_coverage_range_is_0_to_5`
  - `test_formula_applied_and_signal_coverage_are_consistent_teachback_present`
  - `test_formula_applied_and_signal_coverage_are_consistent_teachback_absent`
  - `test_formula_applied_is_literal_type`
  - `test_signal_coverage_is_int_type`
  - `test_openapi_spec_includes_formula_applied`
  - `test_openapi_spec_includes_signal_coverage`
  - `test_no_existing_field_removed_or_renamed` (regression guard)

- [ ] **T6** — Verify `pytest -m unit` exits 0 with all new tests passing and zero regressions.

- [ ] **T7** — Run `python apps/api/scripts/export_openapi.py` and confirm `formula_applied` and
  `signal_coverage` appear in the exported `docs/openapi-assessment.json`.

- [ ] **T8** — Coordinate with Dev 2: share the updated OpenAPI spec excerpt showing the two new
  fields and their `Literal` enum values. Dev 2 must implement UX copy for each `formula_applied`
  variant before the report page can display contextually correct explanations.

---

## Scale & Load

### Q1 — Unit of work and range

One unit = one call to `GET /api/assessment/session/{session_id}/report` for a completed session.

- **Minimum:** Report for a session with zero quiz attempts, zero teachback attempts, and no
  attention data. `signal_coverage = 0`, `formula_applied = 'teachback_redistributed_4_signal'`.
  Response time ≈ 4–6 DB round trips (existing cost; no new DB reads).
- **Typical:** Report for a 30-minute session with 3 segments (9 quiz questions, 3 teachback
  attempts, attention monitoring active). `signal_coverage = 5`.
- **Largest measured:** No new reads are introduced; the load profile is identical to the
  pre-S3-47 `get_session_report`. All new computation is pure Python arithmetic (2 conditionals +
  2 integer assignments).
- **Behaviour beyond range:** Not applicable — the additions are O(1) arithmetic on variables
  already computed earlier in `get_session_report`. There is no new input-size-dependent code path.

### Q2 — Fixed budgets while input varies

No new fixed budgets are introduced. The two new fields are computed from:
- `teachback_score is None` → 1 boolean check (O(1), no DB read)
- `5 if teachback_score is not None else 4` → 1 integer literal (O(1))

No token window, section count, character limit, page count, byte size, timeout, or retry count
is introduced by this story. The `Literal` type annotation in Pydantic is a validation constraint
at the schema level only — it does not add runtime computation.

### Q3 — Scope of every limit

- `formula_applied` and `signal_coverage` are **per-session** fields computed fresh on every
  request from the session's existing DB data. There is no shared state, no per-user cache, and no
  per-deployment accumulation.
- The `Literal` constraint on `formula_applied` is a **per-response** validation that fires at
  Pydantic model construction time. It cannot accumulate across requests.

### Q4 — Unbounded reads and writes

No new DB reads are introduced. No new Redis reads are introduced. No new writes of any kind.

The two new fields are computed from `teachback_score` (already fetched in step 3 of
`get_session_report`) using pure arithmetic. All existing DB queries in `get_session_report`
already carry `.limit()` guards or use `count=` (see existing code; no change here).

### Q5 — Inherited caps re-derived

This story makes no changes to any existing query, window, or limit. It adds no query of its own.
There are no inherited caps to re-derive.

### Q6 — Check-then-act safety under concurrent requests

This story introduces no check-then-act sequence. `formula_applied` and `signal_coverage` are
computed deterministically from `teachback_score` (a read-only DB aggregate that does not change
mid-request). No write is performed. There is no race condition surface.

---

## Security

### Authentication and ownership

The `formula_applied` and `signal_coverage` fields are returned only on an ownership-validated
request. The existing SEC-006 pattern in `get_session_report` (HTTP 404 for both "not found" and
"wrong user" — anti-enumeration oracle) is unchanged. The new fields carry no additional ownership
risk: they reveal only the formula variant applied to the requesting user's own session data.

### Information disclosure

`formula_applied` and `signal_coverage` disclose formula metadata to the authenticated student who
owns the session. This is intentional and required for UX transparency (Jivet et al., 2023;
CLAUDE.md §"No clinical scores shown to students" does not restrict formula metadata — it restricts
raw dimension scores). No competitor-sensitive or security-sensitive information is exposed:
the `Literal` enum values are already documented in the OpenAPI spec.

### Injection

Neither field is derived from user-supplied input. `formula_applied` is a string literal
(`'full_5_signal'` or `'teachback_redistributed_4_signal'`). `signal_coverage` is an integer
literal (4 or 5 in the current implementation). There is no injection surface.

### DPDP Act 2023

No new data collection is introduced. `formula_applied` and `signal_coverage` are synthetic
metadata computed from already-collected `teachback_attempts` counts. DPDP compliance posture is
unchanged.

---

## Test Requirements

All tests in `apps/api/tests/assessment/test_s3_47_formula_applied_signal_coverage.py`.
Tests must use the existing mock pattern (mock Supabase client returning controlled DB rows;
no real DB or Redis connection required). Tests must be tagged `@pytest.mark.unit`.

| Test name | AC covered | What it asserts |
|-----------|------------|-----------------|
| `test_formula_applied_full_5_signal_when_teachback_present` | AC 2 | Exactly `'full_5_signal'` when teachback_attempts rows exist |
| `test_formula_applied_teachback_redistributed_when_teachback_absent` | AC 3 | Exactly `'teachback_redistributed_4_signal'` when teachback_attempts is empty |
| `test_signal_coverage_5_when_teachback_present` | AC 6 | `signal_coverage == 5` when teachback rows exist |
| `test_signal_coverage_4_when_teachback_absent` | AC 7 | `signal_coverage == 4` when teachback rows absent |
| `test_signal_coverage_range_is_0_to_5` | AC 9 | `0 <= signal_coverage <= 5` on both edges |
| `test_formula_applied_and_signal_coverage_are_consistent_teachback_present` | AC 10 | Both fields agree: full_5_signal ↔ coverage=5 |
| `test_formula_applied_and_signal_coverage_are_consistent_teachback_absent` | AC 10 | Both fields agree: teachback_redistributed ↔ coverage=4 |
| `test_formula_applied_is_literal_type` | AC 4 | `get_type_hints(SessionReport)["formula_applied"]` is a `Literal` not bare `str` |
| `test_signal_coverage_is_int_type` | AC 8 | `get_type_hints(SessionReport)["signal_coverage"] is int` |
| `test_openapi_spec_includes_formula_applied` | AC 11 | exported spec has `formula_applied` in `SessionReport` properties |
| `test_openapi_spec_includes_signal_coverage` | AC 12 | exported spec has `signal_coverage` in `SessionReport` properties |
| `test_no_existing_field_removed_or_renamed` | AC 13 | All pre-S3-47 fields still present in `SessionReport` (regression guard) |

---

## Definition of Done

- [ ] `formula_applied` and `signal_coverage` fields added to `SessionReport` in `router.py`
- [ ] Both fields populated in `get_session_report` in `service.py`
- [ ] All 12 unit tests passing (`pytest -m unit` exit 0)
- [ ] `docs/openapi-assessment.json` updated (re-run export script)
- [ ] Dev 2 notified of OpenAPI change and UX copy requirements
- [ ] 6-agent adversarial code review passed (see `CLAUDE.md` — BMAD Code Review Gate)
- [ ] No implementation code committed in the same commit as this story file
