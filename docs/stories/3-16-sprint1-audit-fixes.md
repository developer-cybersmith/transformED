---
baseline_commit: ""
---

# Story 3-16: Sprint 1 Audit Technical Debt Fixes (FIND-001 / FIND-002 / FIND-003)

**Status:** done
**Epic:** Sprint 1 Assessment API — Remediation
**Branch:** `sprint1/s1-16-audit-fixes`
**Depends on:** all Sprint 1 stories merged to main
**Audit source:** FIND-001, FIND-002, FIND-003 from Sprint 1 BMAD Audit Report (2026-07-02)

---

## User Story

As a platform operator,
I want the three open technical debt findings from the Sprint 1 audit resolved,
so that the codebase has no garbled system prompt text, consistent log injection prevention
across both endpoints, and accurate docstring documentation before Sprint 2 begins.

---

## Acceptance Criteria

### AC 1 — Encoding artifact removed from TEACHBACK_SYSTEM_PROMPT (FIND-001)
- `TEACHBACK_SYSTEM_PROMPT` in `prompts.py` does not contain the garbled sequence `â€"`.
- The em-dash appears as the literal `—` character (U+2014) after the fix.
- File is saved as UTF-8.

### AC 2 — Encoding artifact removed from score_teachback() docstring (FIND-001b)
- The `score_teachback()` function docstring in `prompts.py` (line ~118) does not contain `â€"`.
- Second occurrence of the same garbled em-dash fixed in the same commit.

### AC 3 — Log sanitization applied to grade_teachback() insert error path (FIND-002)
- In `service.py` `grade_teachback()` insert error block (~line 434), the raw `insert_error` is no longer passed directly to `logger.error()`.
- A `safe_err` variable is created: `safe_err = str(insert_error).replace('\n', ' ').replace('\r', ' ')` before the log call.
- `logger.error()` receives `safe_err`, not `insert_error` — mirroring the SEC-009 pattern already present in `grade_quiz()`.

### AC 4 — grade_teachback() docstring corrected: wrong-user returns 404 not 403 (FIND-003)
- The `Raises:` section of `grade_teachback()` docstring at ~line 299–303 accurately distinguishes:
  - HTTP 404: session not found, lesson not found, segment not found, **or session belongs to a different user** (SEC-006 enumeration prevention).
  - HTTP 403: `session.lesson_id` does not match request `lesson_id` (IDOR guard only).
- The previous text "HTTPException 403: Session belongs to a different user or to a different lesson" is removed.

### AC 5 — New test: teachback insert error log is sanitized (SEC-009b)
- `test_teachback_insert_error_log_sanitized` added to `tests/test_teachback_endpoint.py`.
- Test patches `logger` in `service.py`, triggers an insert error containing `\n` and `\r`, and asserts that `logger.error` is called with a string containing neither.
- Test mirrors `test_insert_error_log_sanitized` in `test_quiz_endpoint.py`.

### AC 6 — New test: TEACHBACK_SYSTEM_PROMPT has no encoding artifact
- `test_teachback_system_prompt_no_encoding_artifact` added to `tests/test_teachback_endpoint.py`.
- Test imports `TEACHBACK_SYSTEM_PROMPT` from `prompts.py` and asserts the string `"â€"` is not present.

### AC 7 — Full test suite passes with no regressions
- `pytest -m unit` exits 0.
- Minimum test counts: `test_quiz_endpoint.py` ≥ 28, `test_teachback_endpoint.py` ≥ 42 (adds 2 new tests).

---

## Tasks / Subtasks

- [x] Task 1: Write story file — AC: all
  - [x] 1.1 Create `docs/stories/3-16-sprint1-audit-fixes.md`
  - [x] 1.2 Commit story-only, push to remote

- [x] Task 2: RED — write failing tests before applying fixes
  - [x] 2.1 Add `test_teachback_insert_error_log_sanitized` to `test_teachback_endpoint.py` (AC 5)
  - [x] 2.2 Add `test_teachback_system_prompt_no_encoding_artifact` to `test_teachback_endpoint.py` (AC 6)
  - [x] 2.3 Run `pytest -m unit` — confirm both new tests FAIL, existing tests still pass
  - [x] 2.4 Commit RED tests

- [x] Task 3: GREEN — fix prompts.py encoding artifact (AC 1, AC 2)
  - [x] 3.1 Replace `â€"` with `—` at line 73 (TEACHBACK_SYSTEM_PROMPT)
  - [x] 3.2 Replace `â€"` with `—` at line 118 (score_teachback docstring)
  - [x] 3.3 Save file as UTF-8

- [x] Task 4: GREEN — fix service.py log sanitization (AC 3)
  - [x] 4.1 Add `safe_err = str(insert_error).replace('\n', ' ').replace('\r', ' ')` before `logger.error` in `grade_teachback()` insert error block
  - [x] 4.2 Pass `safe_err` to `logger.error()` instead of `insert_error`

- [x] Task 5: GREEN — fix service.py docstring (AC 4)
  - [x] 5.1 Update `grade_teachback()` Raises section to correctly describe 404 for wrong-user, 403 for IDOR lesson mismatch

- [x] Task 6: Run tests and verify GREEN (AC 7)
  - [x] 6.1 `pytest -m unit` → all pass, 0 failures
  - [x] 6.2 Confirm test counts: quiz ≥ 28, teachback ≥ 42

- [x] Task 7: Commit GREEN + push
  - [x] 7.1 `git add` changed files
  - [x] 7.2 Commit with message `fix(dev3/sprint1): B16 GREEN — prompts encoding + teachback log sanitization + docstring`

### Review Findings (5-agent adversarial review — 2026-07-02)

- [x] [Review][Patch] AC 2 missing regression test — no test asserts `score_teachback.__doc__` is free of encoding artifact; add `test_score_teachback_docstring_no_encoding_artifact` [apps/api/tests/test_teachback_endpoint.py]
- [x] [Review][Patch] Missing newline at end of test file — `test_teachback_endpoint.py` last byte is `)` not `\n`; causes ruff W292 lint failure [apps/api/tests/test_teachback_endpoint.py:1310]
- [x] [Review][Defer] ANSI/null-byte log sanitization gap [apps/api/app/modules/assessment/service.py:435] — deferred, pre-existing: `\n`/`\r`-only strip matches the existing grade_quiz() pattern (Story 3-10); ANSI/null/tab not stripped in either endpoint; valid for follow-up story
- [x] [Review][Defer] `exc` from LLM provider logged raw at service.py:385 — deferred, pre-existing: out of scope for FIND-002; affects the score_teachback exception path, not the insert_error path; new finding for future story
- [x] [Review][Defer] Test call_args.args check fragile under f-string refactor [apps/api/tests/test_teachback_endpoint.py:1302] — deferred, pre-existing: not a current failure; only relevant if logger call style changes
- [x] [Review][Defer] _build_supabase_tb routing assumption undocumented — deferred: low priority comment hardening; no correctness issue

---

## Dev Notes

### Files Modified
| File | Change |
|------|--------|
| `apps/api/app/modules/assessment/prompts.py` | Fix 2 encoding artifacts (lines 73, 118) |
| `apps/api/app/modules/assessment/service.py` | Add safe_err sanitization (~line 434), fix docstring (~line 301) |
| `apps/api/tests/test_teachback_endpoint.py` | Add 2 new unit tests (AC 5, AC 6) |

### Files NOT Modified
- `router.py` — no changes needed
- `schemas.py` — no changes needed
- `supabase/migrations/` — never modify applied migrations
- `packages/shared/` — read-only for Dev 3

### SEC-009b Fix Pattern
Mirrors what was applied to `grade_quiz()` in Story 3-10:
```python
# grade_quiz() pattern (correct — Story 3-10):
safe_err = str(insert_resp.error).replace('\n', ' ').replace('\r', ' ')
logger.error("quiz_attempts insert failed: session=%s error=%s", session_id, safe_err)

# grade_teachback() fix (Story 3-16):
safe_err = str(insert_error).replace('\n', ' ').replace('\r', ' ')
logger.error("teachback_attempts insert failed: session=%s error=%s", session_id, safe_err)
```

### Encoding Artifact Details
The garbled sequence `â€"` is the Windows-1252 misread of the UTF-8 em-dash bytes `0xE2 0x80 0x94`:
- `0xE2` → `â` (U+00E2)
- `0x80` → `€` (U+20AC)
- `0x94` → `"` (U+201C)

The fix: replace the 3-char sequence with a literal `—` (U+2014). Two occurrences in `prompts.py`.

---

## Senior Developer Review (AI)

**Review date:** 2026-07-02
**Layers:** Story Quality | Blind Hunter | Test Coverage | AC Completeness | Process Integrity

**Verdict:** APPROVED — all patches applied, 72/72 tests pass.

### Action Items

- [ ] [Patch] Add `test_score_teachback_docstring_no_encoding_artifact` — AC 2 has no regression test
- [ ] [Patch] Add trailing newline to `test_teachback_endpoint.py` — ruff W292 lint issue

### Deferred Findings (not blocking this PR)

- [x] ANSI/null-byte sanitization gap in both endpoints — follow-up story
- [x] Raw `exc` logging at service.py:385 — out of scope, new finding
- [x] Test call_args.args fragility — hypothetical, not a current failure
- [x] _build_supabase_tb comment hardening — low priority

---

## Dev Agent Record

### Completion Notes
All 3 audit findings resolved. 72 unit tests pass (28 quiz + 44 teachback). 5-agent review cleared after adding AC 2 docstring regression test and EOF newline fix. 4 findings deferred to follow-up stories (ANSI sanitization gap in both endpoints, raw exc logging at line 385).

### File List
- `docs/stories/3-16-sprint1-audit-fixes.md` (this file)
- `apps/api/app/modules/assessment/prompts.py`
- `apps/api/app/modules/assessment/service.py`
- `apps/api/tests/test_teachback_endpoint.py`

### Change Log
- 2026-07-02: Story created, Sprint 1 audit technical debt fixes.
