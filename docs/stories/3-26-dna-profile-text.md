---
status: done
baseline_commit: "ca36ff9"
---

# Story 3-26 — Learner DNA Profile Text Generation (GPT-4o-mini)

## Story

As **Dev 4 (WebSocket / tutor state machine)**, after calling `fuse_learner_dna()` which
returns the updated 9-dimension dict, I want an async
`refresh_dna_profile(*, user_id, dims, session_count, supabase, settings)` function
in a new `dna_profile.py` module that reads the current `badge_labels` from the DB,
generates a 2–3 sentence plain-English learning profile via GPT-4o-mini
(`settings.llm_mini`), appends the DPDP Act 2023 disclaimer, and upserts
`learner_dna.profile_text` for that user, so that `GET /api/assessment/user/dna`
always serves fresh descriptive text after each session ends.

## Background & Context

### Why a separate module?
`dna_fusion.py` explicitly documents: *"No LLM calls in this module. Profile text
generation is a separate story (Task 4)."* This story delivers that separation.
Dev 4 calls `fuse_learner_dna()` → gets updated dims → then calls
`refresh_dna_profile()`. Two separate async calls, loosely coupled.

### Relationship to onboarding profile generation
`prompts.py` already contains an analogous function — `generate_onboarding_profile()`
— for the initial onboarding pass. This story ADDS a new prompt and generator for
the post-session update case. The two share `DPDP_DISCLAIMER` (do NOT redefine it).

### Existing DPDP_DISCLAIMER (REUSE — do not recreate)
```python
# Already in prompts.py line 104
DPDP_DISCLAIMER = (
    "This assessment reflects your personal learning preferences, not your intelligence "
    "or capability. TransformED Learner DNA is not a clinical assessment and does not "
    "diagnose any learning or psychological condition. — Pursuant to DPDP Act 2023."
)
```

### Call contract (for Dev 4)
```python
from app.modules.assessment.dna_profile import refresh_dna_profile

# Called AFTER fuse_learner_dna() returns:
updated_dims = await fuse_learner_dna(user_id=..., session_id=..., supabase=..., settings=...)
if updated_dims is not None:
    profile_text = await refresh_dna_profile(
        user_id=user_id,
        dims=updated_dims,          # dict[str, float] — 9 dimensions, 0-100
        session_count=new_count,    # updated count returned by fuse_learner_dna
        supabase=supabase,
        settings=settings,
    )
    # profile_text: str if LLM succeeded, None if LLM failed (non-fatal)
```

### Why descriptors, not raw numbers?
The system prompt and the LLM must NEVER produce raw floats like "75.3" or "67%".
`build_dna_profile_prompt()` translates each dimension value to a descriptor band
before handing context to the LLM. The LLM receives "strong pattern recognition",
not "pattern_recognition: 82.5".

### Descriptor bands
```python
def _dim_descriptor(value: float) -> str:
    if value >= 75.0: return "strong"
    elif value >= 55.0: return "developing"
    elif value >= 35.0: return "building"
    else: return "emerging"
```

### badge_labels source
`badge_labels` lives in `learner_dna` (DB column `text[]`). It is set during
onboarding by `process_onboarding()` and NOT updated by `fuse_learner_dna()`
(per Story 3-25 AC 20). `refresh_dna_profile()` reads the CURRENT stored value
— it does not recompute badges from dims. Badge recomputation is a future story.

### Failure handling
| Failure | Action |
|---------|--------|
| `badge_labels` DB read fails | log WARNING, use `[]`, continue |
| `badge_labels` row not found | use `[]`, continue |
| LLM call raises any exception | log WARNING, return `None` (non-fatal) |
| `profile_text` upsert raises `.error` | log ERROR, raise `HTTPException(503)` |
| `profile_text` upsert raises exception | log ERROR, raise `HTTPException(503)` |

### Cost tracking
Pass `lesson_id=f"dna-profile:{user_id}"` to `OpenAILLMProvider(...)`.
This is consistent with `process_onboarding` which uses `lesson_id="onboarding"`.
Profile text generation with GPT-4o-mini is ~$0.00003 per call — well under
the $3.00/lesson ceiling, but still tracked for observability.

### DB column affected
Only `profile_text` (TEXT, nullable) is written. The upsert payload MUST contain
only `{"user_id": user_id, "profile_text": profile_text}`. NEVER include
badge_labels, the 9 dimension columns, or session_count in this payload —
those are owned by `fuse_learner_dna()` and `process_onboarding()` respectively.

---

## Acceptance Criteria

**AC 1** — `LEARNER_DNA_PROFILE_PROMPT` string constant added to
`apps/api/app/modules/assessment/prompts.py`.

**AC 2** — `LEARNER_DNA_PROFILE_PROMPT` instructs the LLM:
- Never use IQ, EQ, SQ, intelligence quotient, emotional quotient, or any clinical measure
- Never use raw numbers, percentages, or scores
- Write in second person ("You tend to...", "You learn best when...")
- Keep response under 80 words
- Do NOT write the DPDP disclaimer (it is appended by the code automatically)
- Use the dimension descriptors (strong/developing/building/emerging) as context — do NOT repeat them verbatim; translate into natural language

**AC 3** — `_dim_descriptor(value: float) -> str` private helper added to `prompts.py`:
- `value >= 75.0` → `"strong"`
- `value >= 55.0` → `"developing"`
- `value >= 35.0` → `"building"`
- `value < 35.0` → `"emerging"`

**AC 4** — `build_dna_profile_prompt(*, dims, session_count, badge_labels)` function
added to `prompts.py`:
- Accepts `dims: dict[str, float]` (9 dimension values 0-100)
- Accepts `session_count: int`
- Accepts `badge_labels: list[str]`
- Returns a user-turn prompt string
- Each dimension is mapped to its descriptor via `_dim_descriptor()` — raw floats are
  NEVER present in the returned string
- `badge_labels` entries are sanitized against prompt injection:
  `label.replace("<", "&lt;").replace(">", "&gt;")`
- `badge_labels = []` → graceful fallback ("No badges earned yet.")
- `session_count = 0` → handled gracefully ("This is the student's first session.")

**AC 5** — `generate_dna_profile_text(*, dims, session_count, badge_labels, provider)`
async function added to `prompts.py`:
- Calls `provider.complete(messages=[system, user], model=settings.llm_mini)` —
  model comes from `get_settings().llm_mini`, NEVER a hardcoded string
- Returns `f"{llm_text.strip()}\n\n{DPDP_DISCLAIMER}"` — always appends disclaimer

**AC 6** — Every output of `generate_dna_profile_text` ends with the exact
`DPDP_DISCLAIMER` string (verified in tests by `assert result.endswith(DPDP_DISCLAIMER)`).

**AC 7** — `apps/api/app/modules/assessment/dna_profile.py` is created, importable
without error, and exports exactly `__all__ = ["refresh_dna_profile"]`.

**AC 8** — `refresh_dna_profile` async function signature is keyword-only:
```python
async def refresh_dna_profile(
    *,
    user_id: str,
    dims: dict[str, float],
    session_count: int,
    supabase: Any,
    settings: "Settings",
) -> str | None:
```
Positional calls raise `TypeError`.

**AC 9** — Step 1: `refresh_dna_profile` reads `badge_labels` from `learner_dna`
using `asyncio.to_thread`. On DB exception → log WARNING, use `[]`. Row
not found → use `[]`. Both are non-fatal.

**AC 10** — Step 2: `refresh_dna_profile` instantiates
`OpenAILLMProvider(lesson_id=f"dna-profile:{user_id}")` and calls
`generate_dna_profile_text`. On any exception → log WARNING, return `None` (non-fatal).

**AC 11** — Step 3: `refresh_dna_profile` upserts `{"user_id": user_id, "profile_text": profile_text}`
to `learner_dna` with `on_conflict="user_id"`. If `upsert_resp.error` is truthy or
an exception is raised → log ERROR, raise `HTTPException(status_code=503)`.

**AC 12** — Upsert payload contains ONLY `user_id` and `profile_text`. It does NOT
include badge_labels, dimension columns, or session_count (those are owned by other
functions).

**AC 13** — `refresh_dna_profile` returns `str` (the profile_text) on success,
`None` if the LLM call fails.

**AC 14** — `dna_profile.py` has zero `import openai` or `from openai` lines.
Verified by AST scan test.

**AC 15** — `dna_profile.py` has zero hardcoded `"gpt-4o-mini"` string literals.
Verified by AST scan test.

**AC 16** — `generate_dna_profile_text` derives the model from `get_settings().llm_mini`
— no literal model string anywhere in its implementation.

**AC 17** — `build_dna_profile_prompt` output contains no raw floating-point numbers
from `dims`. The only numbers permitted in the output string are the session_count
integer (used in a sentence like "This is session 3 for the student.").

**AC 18** — `badge_labels` injection sanitization: any `<` or `>` characters in a
badge_label are HTML-entity-escaped before the label appears in the prompt string.

**AC 19** — `test_dna_profile.py` at `apps/api/tests/test_dna_profile.py` contains
≥ 20 `@pytest.mark.unit` tests, all passing. Full suite has 0 regressions.

---

## Tasks

- [x] Task 1: Add DNA profile prompt + helpers to prompts.py — ✓ 2026-07-06
  - [x] 1.1 Add `LEARNER_DNA_PROFILE_PROMPT` constant after the `ONBOARDING_PROFILE_SYSTEM_PROMPT` block
  - [x] 1.2 Add `_dim_descriptor(value: float) -> str` private function
  - [x] 1.3 Add `_DIM_LABELS: dict[str, str]` mapping (9 dimension keys → human-readable labels)
  - [x] 1.4 Add `build_dna_profile_prompt(*, dims, session_count, badge_labels) -> str` function
    - [x] 1.4a Map each dim through `_dim_descriptor()` and `_DIM_LABELS`
    - [x] 1.4b Sanitize badge_labels: `label.replace("<", "&lt;").replace(">", "&gt;")`
    - [x] 1.4c Handle empty badge_labels → "No badges earned yet."
    - [x] 1.4d Handle session_count = 0 → "This is the student's first session."
    - [x] 1.4e Handle session_count > 0 → f"This is session {session_count} for the student."
  - [x] 1.5 Add `generate_dna_profile_text(*, dims, session_count, badge_labels, provider) -> Coroutine[str]`
    - [x] 1.5a Build messages list (system = LEARNER_DNA_PROFILE_PROMPT, user = build_dna_profile_prompt(...))
    - [x] 1.5b Call `provider.complete(messages=messages, model=settings.llm_mini)`
    - [x] 1.5c Return `f"{llm_text.strip()}\n\n{DPDP_DISCLAIMER}"`

- [x] Task 2: Create apps/api/app/modules/assessment/dna_profile.py — ✓ 2026-07-06
  - [x] 2.1 Module docstring explaining separation from dna_fusion.py + no-LLM rule
  - [x] 2.2 `from __future__ import annotations` + imports (asyncio, logging, TYPE_CHECKING)
  - [x] 2.3 `__all__ = ["refresh_dna_profile"]`
  - [x] 2.4 Implement `refresh_dna_profile(*, user_id, dims, session_count, supabase, settings)`
    - [x] 2.4a `OpenAILLMProvider` imported at MODULE LEVEL (not local) for test patchability; `from fastapi import HTTPException, status` and `from app.modules.assessment.prompts import generate_dna_profile_text` remain as local imports inside function
    - [x] 2.4b Step 1 — read badge_labels from learner_dna (asyncio.to_thread, non-fatal failure)
    - [x] 2.4c Step 2 — `OpenAILLMProvider(lesson_id=f"dna-profile:{user_id}")`; call `generate_dna_profile_text`; on exception log WARNING + return None
    - [x] 2.4d Step 3 — upsert `{"user_id": user_id, "profile_text": profile_text}` on_conflict="user_id"; handle `.error` + exception → HTTPException(503)
    - [x] 2.4e `logger.info(...)` on success; return profile_text

- [x] Task 3: Write apps/api/tests/test_dna_profile.py (RED → GREEN) — ✓ 2026-07-06
  - [x] 3.1 `test_dunder_all_exports_only_refresh_dna_profile`
  - [x] 3.2 `test_positional_args_raise_type_error`
  - [x] 3.3 `test_dim_descriptor_strong` — 82.0 → "strong"
  - [x] 3.4 `test_dim_descriptor_developing` — 62.0 → "developing"
  - [x] 3.5 `test_dim_descriptor_building` — 45.0 → "building"
  - [x] 3.6 `test_dim_descriptor_emerging` — 20.0 → "emerging"
  - [x] 3.7 `test_dim_descriptor_boundary_75_is_strong` — exactly 75.0 → "strong"
  - [x] 3.8 `test_build_prompt_contains_no_raw_floats` — assert no "." followed by digits in dim section
  - [x] 3.9 `test_build_prompt_with_badges_includes_badge_text`
  - [x] 3.10 `test_build_prompt_empty_badges_says_no_badges`
  - [x] 3.11 `test_build_prompt_sanitizes_injection_in_badge_labels`
  - [x] 3.12 `test_build_prompt_session_count_zero_says_first_session`
  - [x] 3.13 `test_build_prompt_session_count_positive`
  - [x] 3.14 `test_generate_profile_text_appends_dpdp_disclaimer`
  - [x] 3.15 `test_generate_profile_text_uses_llm_mini_from_settings`
  - [x] 3.16 `test_refresh_dna_profile_success_returns_profile_text`
  - [x] 3.17 `test_refresh_dna_profile_upsert_payload_only_has_user_id_and_profile_text`
  - [x] 3.18 `test_refresh_dna_profile_llm_failure_returns_none`
  - [x] 3.19 `test_refresh_dna_profile_upsert_failure_raises_503`
  - [x] 3.20 `test_refresh_dna_profile_badge_labels_read_failure_continues_with_empty`
  - [x] 3.21 `test_refresh_dna_profile_badge_labels_row_not_found_uses_empty`
  - [x] 3.22 `test_no_openai_import_in_dna_profile` (AST scan — checks top-level PyPI `openai` only, allows `app.providers.llm.openai`)
  - [x] 3.23 `test_no_hardcoded_model_string_in_dna_profile` (AST scan)

- [x] Task 4: Run full test suite — AC 19 — ✓ 2026-07-06
  - [x] 4.1 `pytest -m unit tests/test_dna_profile.py` → 29/29 passed (post-review: 23 original + 6 new)
  - [x] 4.2 Full suite `pytest -m unit` → 506 passed, 0 new regressions (29 pre-existing failures in Dev4 modules unrelated to Task 4)

---

## Dev Notes

### Files being MODIFIED
```
apps/api/app/modules/assessment/prompts.py   — ADD ~60 lines after ONBOARDING block
```

### Files being CREATED (NEW)
```
apps/api/app/modules/assessment/dna_profile.py   — NEW ~90 lines
apps/api/tests/test_dna_profile.py               — NEW ~23 unit tests
```

### Files NOT touched
```
apps/api/app/modules/assessment/dna_fusion.py    — no changes (profile text is separate)
apps/api/app/modules/assessment/router.py        — no new endpoints
apps/api/app/modules/assessment/service.py       — no changes
apps/api/app/config.py                           — no new settings (uses existing llm_mini)
apps/api/app/modules/assessment/schemas.py       — no changes
supabase/migrations/                             — never modify applied migrations
packages/shared/                                 — read-only for Dev 3
```

### Exact pattern for asyncio.to_thread (match dna_fusion.py exactly)
```python
dna_resp = await asyncio.to_thread(
    lambda: supabase.table("learner_dna")
    .select("badge_labels")
    .eq("user_id", user_id)
    .maybe_single()
    .execute()
)
```

### Local import pattern (avoids circular imports — mandatory)
```python
async def refresh_dna_profile(*, ...):
    from fastapi import HTTPException, status         # local
    from app.modules.assessment.prompts import generate_dna_profile_text  # local
    from app.providers.llm.openai import OpenAILLMProvider                # local
    ...
```

### _DIM_LABELS mapping (exact values — copy verbatim)
```python
_DIM_LABELS: dict[str, str] = {
    "pattern_recognition":   "pattern recognition",
    "logical_deduction":     "logical reasoning",
    "processing_speed":      "processing speed",
    "frustration_tolerance": "resilience under pressure",
    "persistence":           "persistence",
    "help_seeking":          "collaborative learning",
    "goal_orientation":      "goal orientation",
    "curiosity_index":       "curiosity",
    "study_independence":    "study independence",
}
```

### _settings() test helper (match test_dna_fusion.py pattern)
```python
def _settings():
    from unittest.mock import MagicMock
    s = MagicMock()
    s.llm_mini = "gpt-4o-mini"
    s.openai_api_key = "test-key"
    return s
```

### Supabase mock helper for test_dna_profile.py
```python
from unittest.mock import MagicMock

def _supabase_mock(
    badge_labels: list[str] | None = None,
    upsert_raises: bool = False,
    badge_read_raises: bool = False,
):
    """Mock supabase.table() routed by table name."""
    supabase = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _table(name):
        tbl = MagicMock()
        if name == "learner_dna":
            if badge_read_raises:
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = Exception("DB read failed")
            else:
                row = {"badge_labels": badge_labels} if badge_labels is not None else None
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(row)
            if upsert_raises:
                tbl.upsert.return_value.execute.side_effect = Exception("DB write failed")
            else:
                tbl.upsert.return_value.execute.return_value = _resp([])
        return tbl

    supabase.table.side_effect = _table
    return supabase
```

### Mock provider pattern
```python
async def _mock_provider_complete(messages, model):
    return "You have a strong ability to recognise patterns and think logically."

provider = MagicMock()
provider.complete = AsyncMock(return_value="You have a strong ability to recognise patterns.")
```

### AST scan pattern (match test_dna_fusion.py)
```python
import ast, pathlib

def test_no_openai_import_in_dna_profile():
    src = pathlib.Path("app/modules/assessment/dna_profile.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            for alias in getattr(node, "names", []):
                assert "openai" not in (alias.name or ""), \
                    f"Direct openai import found: {alias.name}"
            assert "openai" not in module, f"Direct openai module import: {module}"

def test_no_hardcoded_model_string_in_dna_profile():
    src = pathlib.Path("app/modules/assessment/dna_profile.py").read_text()
    assert "gpt-4o-mini" not in src, "Hardcoded model string found in dna_profile.py"
    assert "gpt-4o" not in src, "Hardcoded model string found in dna_profile.py"
```

### Critical: generate_dna_profile_text must call get_settings()
```python
# CORRECT — settings.llm_mini is resolved at call time
async def generate_dna_profile_text(*, dims, session_count, badge_labels, provider):
    settings = get_settings()  # ← existing import at top of prompts.py
    ...
    llm_text = await provider.complete(messages=messages, model=settings.llm_mini)
```

### Test for upsert payload correctness
```python
async def test_refresh_dna_profile_upsert_payload_only_has_user_id_and_profile_text():
    supabase = _supabase_mock(badge_labels=["Pattern Thinker"])
    upsert_calls = []

    original_side_effect = supabase.table.side_effect
    def tracking_table(name):
        tbl = original_side_effect(name)
        if name == "learner_dna":
            orig_upsert = tbl.upsert
            def capture_upsert(payload, **kwargs):
                upsert_calls.append(dict(payload))
                return orig_upsert(payload, **kwargs)
            tbl.upsert = capture_upsert
        return tbl
    supabase.table.side_effect = tracking_table

    with patch("app.modules.assessment.dna_profile.refresh_dna_profile.__wrapped__", ...):
        ...  # call refresh_dna_profile

    assert len(upsert_calls) == 1
    payload = upsert_calls[0]
    assert set(payload.keys()) == {"user_id", "profile_text"}
    # Dimension columns must NOT appear
    forbidden = {"pattern_recognition", "logical_deduction", "badge_labels", "session_count"}
    assert not (forbidden & set(payload.keys()))
```

Note: the upsert payload verification test is tricky with the lambda pattern.
Use the `_supabase_mock` helper's `tbl.upsert.call_args` inspection instead:

```python
# After calling refresh_dna_profile(...)
learner_dna_tbl_mock = supabase.table.side_effect.__closure__  # brittle
# Instead: capture via side_effect override in _supabase_mock:
# Add upsert_calls capture to _supabase_mock, then inspect after the call.
```

Simpler approach for the payload test — use a custom inline supabase mock:
```python
async def test_refresh_dna_profile_upsert_payload_only_has_user_id_and_profile_text():
    captured = {}

    supabase = MagicMock()
    def _resp(data): r = MagicMock(); r.data = data; r.error = None; return r
    def _table(name):
        tbl = MagicMock()
        if name == "learner_dna":
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp({"badge_labels": []})
            def _upsert(payload, **kwargs):
                captured["payload"] = dict(payload)
                mock_resp = MagicMock(); mock_resp.error = None; mock_resp.data = []
                result = MagicMock(); result.execute.return_value = mock_resp
                return result
            tbl.upsert.side_effect = _upsert
        return tbl
    supabase.table.side_effect = _table

    # Mock provider
    provider_instance = MagicMock()
    provider_instance.complete = AsyncMock(return_value="You are a strong learner.")

    with patch("app.modules.assessment.dna_profile.OpenAILLMProvider", return_value=provider_instance):
        result = await refresh_dna_profile(
            user_id="u1", dims=_all_dims(75.0), session_count=3,
            supabase=supabase, settings=_settings()
        )

    assert set(captured["payload"].keys()) == {"user_id", "profile_text"}
```

### Rule: no session_id parameter
`refresh_dna_profile` does NOT take a `session_id` parameter. It is a user-level
operation (profile_text is per-user, not per-session). This is different from
`fuse_learner_dna` which needs session_id to read quiz/teachback/events data.

### Rule: no badge recomputation
Do NOT recompute `badge_labels` in this function. Read from DB as-is. Badge
computation from DNA dimensions is a future story (not Task 4).

### Rule: generate every time, not just every 3rd session
The tracker says "Regenerate after every Learner DNA update". Implement as
"always regenerate when called." The calling code controls when to invoke
`refresh_dna_profile`. Do NOT add an internal `if session_count % 3 == 0` gate —
the caller decides frequency.

---

## Dev Agent Record

### Debug Log

- **`AttributeError: OpenAILLMProvider` in tests (7 tests failing)** — Story Dev Notes specified `OpenAILLMProvider` as a local import inside `refresh_dna_profile()`. However, `patch("app.modules.assessment.dna_profile.OpenAILLMProvider")` requires the name to exist at module level. Fix: moved `from app.providers.llm.openai import OpenAILLMProvider` to module level. AC 14 still satisfied — this is our provider abstraction, not the `openai` PyPI package.

- **`AssertionError: openai ImportFrom found in dna_profile.py` (1 test failing)** — AST test `test_no_openai_import_in_dna_profile` used substring check `"openai" not in module` which incorrectly flagged `app.providers.llm.openai`. AC 14 means the PyPI `openai` package only. Fix: updated test to check `module.split(".")[0] != "openai"` (top-level package check only).

### Completion Notes

- 3 new functions + 1 constant added to `prompts.py`: `LEARNER_DNA_PROFILE_PROMPT`, `_dim_descriptor()`, `build_dna_profile_prompt()`, `generate_dna_profile_text()`. Reuses existing `DPDP_DISCLAIMER` — not redefined.
- `dna_profile.py` created: single exported function `refresh_dna_profile()`. `OpenAILLMProvider` at module level (not local) for test patchability. `fastapi` and `prompts` imports remain local to avoid circular import risk.
- 23 unit tests, all GREEN. AST scans verify no PyPI `openai` imports and no hardcoded model strings.
- 500 existing tests still pass. 29 pre-existing failures all in Dev 4 modules (missing `langgraph`, missing env vars) — none introduced by this story.

### File List

| File | Action |
|------|--------|
| `apps/api/app/modules/assessment/prompts.py` | MODIFY — add LEARNER_DNA_PROFILE_PROMPT + 3 functions |
| `apps/api/app/modules/assessment/dna_profile.py` | CREATE |
| `apps/api/tests/test_dna_profile.py` | CREATE |

### Change Log

| Date | Change |
|------|--------|
| 2026-07-06 | Story created — Sprint 3 Task 4 |
| 2026-07-06 | Implementation complete — Tasks 1-4 done, 23 tests GREEN, status → review |
| 2026-07-06 | Code review BLOCKERs addressed (R1-R11 + Option B) — 29 tests GREEN, 0 regressions, status → done |

---

## Senior Developer Review (AI)

**Review date:** 2026-07-06
**Outcome:** Changes Requested
**Layers run:** Story Quality, Blind Hunter (Security), Test Coverage / Edge Case Hunter, AC Completeness, Process Integrity
**Summary:** 3 BLOCKERs (AC failures), 1 HIGH security, 2 additional security patches, 5 test-coverage patches, 1 decision needed. Process Integrity: all 13 rules PASS.

### Review Follow-ups (AI)

**Decision-needed:**
- [x] [Review][Decision] R12: RESOLVED via Option B — `generate_dna_profile_text` now accepts `settings: Any` parameter; `refresh_dna_profile` forwards `settings=settings`. Dead parameter eliminated. — ✓ 2026-07-06

**BLOCKERs — resolved:**
- [x] [Review][Patch] R1: AC 10 — `OpenAILLMProvider(...)` moved inside try/except block; constructor failures now non-fatal (return None) — ✓ 2026-07-06
- [x] [Review][Patch] R2: AC 11/AC 19 — `test_refresh_dna_profile_upsert_error_field_raises_503` added; `_supabase_mock(upsert_error=True)` path now covered — ✓ 2026-07-06
- [x] [Review][Patch] R3: AC 2 — `test_learner_dna_profile_prompt_content` added; verifies IQ/EQ/SQ prohibition, second-person rule, no DPDP Act 2023 text in prompt — ✓ 2026-07-06

**Security patches — resolved:**
- [x] [Review][Patch] R4: SEC-HIGH — `bl.replace('\n', ' ').replace('\r', ' ')` added before HTML escape in `build_dna_profile_prompt`; `test_build_prompt_sanitizes_newlines_in_badge_labels` added — ✓ 2026-07-06
- [x] [Review][Patch] R5: SEC-MEDIUM — `_safe_uid = str(user_id).replace('\n', ' ').replace('\r', ' ')` added; used in all 3 logger calls — ✓ 2026-07-06
- [x] [Review][Patch] R6: SEC-LOW — `safe_err` now strips both `\n` and `\r` — ✓ 2026-07-06

**Test-coverage patches — resolved:**
- [x] [Review][Patch] R7: `on_conflict="user_id"` kwarg assertion added to upsert payload test — ✓ 2026-07-06
- [x] [Review][Patch] R8: `messages[0]["content"] == LEARNER_DNA_PROFILE_PROMPT` assertion added to test 15 — ✓ 2026-07-06
- [x] [Review][Patch] R9: `mock_llm_class.assert_called_once_with(lesson_id="dna-profile:u1")` added to test 16 — ✓ 2026-07-06
- [x] [Review][Patch] R10: `test_dim_descriptor_boundary_55_is_developing` and `test_dim_descriptor_boundary_35_is_building` added — ✓ 2026-07-06
- [x] [Review][Patch] R11: All DPDP_DISCLAIMER checks changed from `in` to `endswith` in tests 16, 20, 21 — ✓ 2026-07-06

**Deferred (pre-existing / design):**
- [x] [Review][Defer] R13: IDOR — `refresh_dna_profile` has no caller-identity guard; service-role client bypasses RLS — deferred, internal API contract (Dev 4 owns JWT auth, user_id from JWT-decoded sub)
- [x] [Review][Defer] R14: dims NaN/Inf not validated before `_dim_descriptor` comparisons — deferred, upstream fusion (`dna_fusion.py`) is the validation boundary, not in AC scope
- [x] [Review][Defer] R15: AST hardcoded-model scan covers only `dna_profile.py`, not `prompts.py` — deferred, behavioral test (test 15) already catches this regression path
