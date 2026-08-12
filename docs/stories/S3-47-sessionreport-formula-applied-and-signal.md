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

**Decision record reference:** `docs/architecture/CES_DECISION_RECORD.md` section 21 — D17 approves Option A:
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
string field. The field is present in every non-error 200 OK response, regardless of whether
teach-back was attempted.

Verified by: `assert "formula_applied" in report_dict`.

---

### AC 2 — formula_applied == 'full_5_signal' when teach-back was submitted

When the session has at least one row in `teachback_attempts` (i.e., `teachback_score is not None`
in the report computation), `formula_applied` is exactly the string `'full_5_signal'`.

Verified by: constructing a mock session with one `teachback_attempts` row, calling
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

The field annotation must be a `Literal` type, not bare `str`. Pydantic will reject any value not
in the `Literal` at model construction time — the runtime guard is the type itself.

Verified by: `import typing; assert typing.get_type_hints(SessionReport)["formula_applied"] == Literal['full_5_signal', 'teachback_redistributed_4_signal']`.

---

### AC 5 — signal_coverage field present in SessionReport response

`GET /api/assessment/session/{id}/report` returns a JSON object that includes a `signal_coverage`
integer field. The field is present in every non-error 200 OK response.

Verified by: `assert "signal_coverage" in report_dict`.

---

### AC 6 — signal_coverage == 5 when teach-back is present

When `teachback_score is not None` (at least one `teachback_attempts` row), `signal_coverage == 5`.

Rationale: All five CES signals (quiz, teachback, behavioral, head_pose, blink) are counted as
present in the 5-signal formula variant. Behavioral/head_pose/blink are always included in the
formula computation (even if their contribution is 0.0 when no attention data is available). When
teach-back is present, the formula operates in full 5-signal mode.

Verified by: mock session with one `teachback_attempts` row → `assert report.signal_coverage == 5`.

---

### AC 7 — signal_coverage == 4 when teach-back is skipped

When `teachback_score is None` (zero `teachback_attempts` rows), `signal_coverage == 4`.

Rationale: Teach-back is the only signal excluded from the formula when absent — its weight is
redistributed to the remaining four signals. `signal_coverage` reflects the count of signals
entering the formula: 4 when teach-back is excluded, 5 when all signals are present.

Verified by: mock session with zero `teachback_attempts` rows → `assert report.signal_coverage == 4`.

---

### AC 8 — signal_coverage type is int in the Pydantic model

`SessionReport.signal_coverage` is typed as `int` (not `float`, not `str`, not `Optional[int]`).

Verified by: `import typing; assert typing.get_type_hints(SessionReport)["signal_coverage"] is int`.

---

### AC 9 — signal_coverage range is enforced [0, 5]

The implementation guarantees `0 <= signal_coverage <= 5` for all possible session states. A unit
test constructs edge-case inputs (all signals absent: signal_coverage == 0 conceptually, but
current implementation yields 4 minimum; all signals present: signal_coverage == 5) and asserts
the field stays within the declared range in every case.

Verified by: `assert 0 <= report.signal_coverage <= 5` across both edge cases.

---

### AC 10 — formula_applied and signal_coverage are consistent with each other

In every test scenario, the mapping `formula_applied == 'full_5_signal'` iff
`signal_coverage == 5` must hold — these two fields must not disagree.

Verified by: parametrize over (teachback_present=True, teachback_present=False) and in both cases
assert that both fields agree on the formula variant.

---

### AC 11 — formula_applied appears in the OpenAPI spec

Running `python apps/api/scripts/export_openapi.py` and parsing the resulting JSON confirms that
the schema named `SessionReport` in the spec's `components.schemas` includes `formula_applied` as
a property.

Verified by:
```python
assert "formula_applied" in spec["components"]["schemas"]["SessionReport"]["properties"]
```

---

### AC 12 — signal_coverage appears in the OpenAPI spec

Same as AC 11 but for `signal_coverage`.

Verified by:
```python
assert "signal_coverage" in spec["components"]["schemas"]["SessionReport"]["properties"]
```

---

### AC 13 — Additive only: all pre-S3-47 SessionReport fields remain unchanged

The addition of `formula_applied` and `signal_coverage` must not alter any existing field name,
type, or default. The full `pytest -m unit` test suite (including tests from Stories 3-19, 3-29,
3-30, and all earlier session report stories) must remain green without modification.

Verified by: `pytest -m unit` exit code 0 with zero failures and zero errors.

---

### AC 14 — No migration, no Redis change, no LLM call

The implementation modifies exactly two Python files:
- `apps/api/app/modules/assessment/router.py` — two new fields on `SessionReport`
- `apps/api/app/modules/assessment/service.py` — two new lines in `get_session_report`

No new migration file is created. No Redis key is read or written. No LLM provider is called.
No new DB table or column is created.

Verified by: `git diff --name-only` after implementation shows only those two files plus the new
test file.

---

## Tasks / Subtasks

- [ ] **T1** — Add `formula_applied: Literal['full_5_signal', 'teachback_redistributed_4_signal']`
  to `SessionReport` in `apps/api/app/modules/assessment/router.py`. Import `Literal` from
  `typing` at the top of the file (it is not yet imported there). Place the field after
  `learner_dna_snapshot` to preserve stable field ordering for existing consumers.

- [ ] **T2** — Add `signal_coverage: int` to `SessionReport` in the same file, immediately after
  `formula_applied`. No default value — both fields are required and always populated.

- [ ] **T3** — In `apps/api/app/modules/assessment/service.py:get_session_report`, after step 3
  (teachback stats, where `teachback_score` is established), add:
  ```python
  formula_applied = (
      "teachback_redistributed_4_signal" if teachback_score is None else "full_5_signal"
  )
  signal_coverage = 4 if teachback_score is None else 5
  ```
  Both variables must be computed before the `SessionReport(...)` constructor at the end of
  `get_session_report`.

- [ ] **T4** — Pass `formula_applied=formula_applied` and `signal_coverage=signal_coverage` to the
  `SessionReport(...)` constructor at the end of `get_session_report`.

- [ ] **T5** — Write 12 unit tests in
  `apps/api/tests/assessment/test_s3_47_formula_applied_signal_coverage.py` (see Test
  Requirements section).

- [ ] **T6** — Verify `pytest -m unit` exits 0 with all new tests passing and zero regressions.

- [ ] **T7** — Run `python apps/api/scripts/export_openapi.py` and confirm both new fields appear
  in `docs/openapi-assessment.json` under the `SessionReport` schema.

- [ ] **T8** — Notify Dev 2: share the updated OpenAPI spec excerpt. Dev 2 must implement UX copy
  for each `formula_applied` variant before the session report page can display contextually
  appropriate explanations.

---

## Scale & Load

### Q1 — Unit of work and range

One unit = one call to `GET /api/assessment/session/{session_id}/report` for a completed session.

- **Minimum:** Session with zero quiz attempts, zero teachback attempts. `signal_coverage = 4`,
  `formula_applied = 'teachback_redistributed_4_signal'`. Response time unchanged — no new DB
  reads.
- **Typical:** 30-minute session with 3 segments (9 quiz questions, 3 teachback attempts).
  `signal_coverage = 5`, `formula_applied = 'full_5_signal'`.
- **Largest measured:** The pre-S3-47 `get_session_report` determines the load profile. All new
  computation is O(1) arithmetic: one boolean comparison and one integer assignment. No additional
  DB reads, Redis reads, or LLM calls.
- **Behaviour beyond range:** Not applicable — there is no variable input feeding into the new
  computation. The output is a deterministic function of `teachback_score is None`, which is
  already computed earlier in the function.

### Q2 — Fixed budgets while input varies

No new fixed budgets are introduced. The two new fields are O(1) derivations of a boolean:

- `formula_applied`: one string literal selection (no allocation beyond the string intern)
- `signal_coverage`: one integer literal (4 or 5)

No token window, section count, character limit, page count, byte size, timeout, or retry count
is added. The `Literal` constraint in Pydantic adds a constant-time enum check at model
construction, not a per-input scan.

### Q3 — Scope of every limit

- `formula_applied` and `signal_coverage` are **per-session** fields computed freshly on every
  report request from the session's DB data. No shared mutable state, no per-user accumulation,
  no per-deployment budget.
- The `Literal` validation is **per-response** (Pydantic model construction). It cannot
  accumulate across requests or instances.

### Q4 — Unbounded reads and writes

No new DB reads are introduced. No new Redis reads or writes. No new writes of any kind.

`formula_applied` and `signal_coverage` are derived from `teachback_score`, which is already
fetched in step 3 of `get_session_report` via a bounded query:
```python
supabase.table("teachback_attempts").select("score").eq("session_id", session_id).execute()
```
This query has a natural bound: one row per segment per attempt per session. The pre-existing
`.limit()` analysis from Story 3-19 applies unchanged.

### Q5 — Inherited caps re-derived

This story adds no queries and introduces no new caps. All existing caps in `get_session_report`
(quiz_attempts select, teachback_attempts select, session_events count, learner_dna select) are
unchanged. No re-derivation is required.

### Q6 — Check-then-act safety under concurrent requests

This story introduces no check-then-act sequence. `formula_applied` and `signal_coverage` are
computed deterministically from the already-fetched `teachback_score` value (a read-only aggregate
that does not change after session end). No write is performed. There is no race condition surface.

---

## Security

### Authentication and ownership

`formula_applied` and `signal_coverage` are returned only after the existing SEC-006 ownership
check in `get_session_report`: the endpoint returns HTTP 404 for both "session not found" and
"session belongs to a different user", preventing session enumeration. The new fields carry no
additional ownership risk — they reveal formula metadata about the requesting user's own session.

### Information disclosure

`formula_applied` discloses which formula variant was applied. The two `Literal` values
(`'full_5_signal'`, `'teachback_redistributed_4_signal'`) are publicly documented in the OpenAPI
spec and reveal nothing beyond what is already implied by `ces_breakdown` structure. This
disclosure is intentional and required for UX transparency (CLAUDE.md §"No clinical scores shown
to students" restricts raw dimension scores, not formula metadata).

`signal_coverage` is an integer in [0, 5]. It reveals the count of signals in the formula but not
their individual values. No sensitive data is exposed.

### Injection

Neither field is derived from user-supplied input. `formula_applied` is a string literal from a
closed two-value `Literal` enum. `signal_coverage` is an integer literal (4 or 5 in the current
implementation). There is no injection surface.

### DPDP Act 2023

No new data collection. Both fields are synthetic metadata computed from already-persisted
`teachback_attempts` counts. DPDP compliance posture is unchanged.

---

## Test Requirements

All tests in `apps/api/tests/assessment/test_s3_47_formula_applied_signal_coverage.py`.
Tests use the existing Supabase mock pattern (controlled mock returning DB rows; no real DB or
Redis connection). All tests tagged `@pytest.mark.unit`.

| Test name | AC covered | What it asserts |
|-----------|------------|-----------------|
| `test_formula_applied_full_5_signal_when_teachback_present` | AC 2 | `report.formula_applied == 'full_5_signal'` when teachback_attempts rows exist |
| `test_formula_applied_teachback_redistributed_when_teachback_absent` | AC 3 | `report.formula_applied == 'teachback_redistributed_4_signal'` when zero teachback rows |
| `test_signal_coverage_5_when_teachback_present` | AC 6 | `report.signal_coverage == 5` when teachback rows exist |
| `test_signal_coverage_4_when_teachback_absent` | AC 7 | `report.signal_coverage == 4` when zero teachback rows |
| `test_signal_coverage_range_is_0_to_5` | AC 9 | `0 <= report.signal_coverage <= 5` on both edges |
| `test_formula_applied_and_signal_coverage_consistent_teachback_present` | AC 10 | Both fields agree: `'full_5_signal'` ↔ coverage=5 |
| `test_formula_applied_and_signal_coverage_consistent_teachback_absent` | AC 10 | Both fields agree: `'teachback_redistributed_4_signal'` ↔ coverage=4 |
| `test_formula_applied_is_literal_type` | AC 4 | `get_type_hints(SessionReport)["formula_applied"]` is a `Literal` not bare `str` |
| `test_signal_coverage_is_int_type` | AC 8 | `get_type_hints(SessionReport)["signal_coverage"] is int` |
| `test_openapi_spec_includes_formula_applied` | AC 11 | Exported spec has `formula_applied` in `SessionReport` properties |
| `test_openapi_spec_includes_signal_coverage` | AC 12 | Exported spec has `signal_coverage` in `SessionReport` properties |
| `test_no_existing_field_removed_or_renamed` | AC 13 | All pre-S3-47 `SessionReport` fields still present (regression guard) |

---

## Definition of Done

- [ ] `formula_applied` and `signal_coverage` added to `SessionReport` in `router.py`
- [ ] Both fields populated in `get_session_report` in `service.py`
- [ ] All 12 unit tests passing (`pytest -m unit` exits 0)
- [ ] `docs/openapi-assessment.json` updated (re-run export script)
- [ ] Dev 2 notified of OpenAPI change and UX copy requirements
- [ ] 6-agent adversarial code review passed (CLAUDE.md — BMAD Code Review Gate)
- [ ] No implementation code committed in the same commit as this story file
