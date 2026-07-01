# Dev 1 Handoff: Content Pipeline & Pub/Sub Test Failures — Root Cause & Fix

**From:** Dev 3 (tannmayygupta)
**To:** Dev 1 (Content pipeline + infra owner)
**Date:** 2026-06-27
**Failing branch:** `main` (pre-existing — present in all branches, not caused by any Dev 3 changes)
**Severity:** Medium — 5 tests fail across two distinct root causes; all Dev 3 tests unaffected
**Status:** Awaiting Dev 1 fix — these failures appear in every test run on every branch

---

## TL;DR — Two Bugs, Two Fixes

**Bug 1 (tests 1, 2, 5):** `pipeline/__init__.py` is empty → `graph` submodule not in package namespace → patch fails

```python
# apps/api/app/modules/content/pipeline/__init__.py
from . import graph
```

**Bug 2 (tests 3, 4):** `_run_lesson_subscriber` in `app/core/pubsub.py` calls bare `get_settings()` → pydantic ValidationError for 9 missing env vars → add a `_mock_settings` fixture

```python
# apps/api/tests/test_lesson_ready_pubsub.py — add this fixture
@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    mock = MagicMock()
    mock.redis_url = "redis://localhost:6379"
    monkeypatch.setattr("app.core.pubsub.get_settings", lambda: mock)
```

---

## 1. Failing Tests

**File:** `apps/api/tests/test_lesson_ready_pubsub.py`

```
FAILED tests/test_lesson_ready_pubsub.py::test_publish_channel_uses_session_id
FAILED tests/test_lesson_ready_pubsub.py::test_publish_message_has_correct_ws_shape
FAILED tests/test_lesson_ready_pubsub.py::test_subscriber_forwards_pmessage_to_manager
FAILED tests/test_lesson_ready_pubsub.py::test_subscriber_handles_malformed_json
FAILED tests/test_lesson_ready_pubsub.py::test_routing_reaches_correct_client_when_session_id_differs
```

---

## 2. Bug 1 — Empty `pipeline/__init__.py` (Tests 1, 2, 5)

### Exact error

```
AttributeError: module 'app.modules.content.pipeline' has no attribute 'graph'

tests\test_lesson_ready_pubsub.py:70: in _patch_pipeline_deps
    mocker.patch(
        "app.modules.content.pipeline.graph.run_pipeline",
        new=AsyncMock(return_value=lesson_package),
    )

C:\...\pkgutil.py:528: in resolve_name
    result = getattr(result, p)
             ^^^^^^^^^^^^^^^^^^
AttributeError: module 'app.modules.content.pipeline' has no attribute 'graph'
```

The error fires at `mocker.patch(...)` setup — before any test logic runs.

### Package structure

```
apps/api/app/modules/content/
├── __init__.py
├── router.py
├── service.py
└── pipeline/
    ├── __init__.py   ← EMPTY (1 line, no content) — this is the problem
    ├── graph.py      ← defines run_pipeline() at line 380
    └── nodes/        ← 11 LangGraph pipeline nodes
```

### Root cause

In Python 3.12, `pytest-mock` delegates to `pkgutil.resolve_name`. That function:

1. Imports `app.modules.content.pipeline` via `importlib.import_module`
2. Calls `getattr(pipeline_module, 'graph')` to get the `graph` submodule
3. Because `pipeline/__init__.py` is **empty**, `graph` was never imported into the package namespace
4. `getattr` raises `AttributeError` — no fallback in Python 3.12's resolver

`run_pipeline` itself IS defined in `graph.py` at line 380:
```python
async def run_pipeline(lesson_id: str, chapter_content: str, user_id: str = "") -> dict[str, Any]:
```

The function exists. The resolver just can't reach it because `graph` isn't in the package namespace.

### Fix

**File:** `apps/api/app/modules/content/pipeline/__init__.py`

```python
from . import graph
```

This is the complete file content after the fix. One line. No other files change.

**Why safe:** `graph.py` imports LangGraph and defines the pipeline graph at module level.
These load when `pipeline` is imported — which only happens when the content router loads,
not at test collection. Lazy import patterns inside node functions remain unchanged.

---

## 3. Bug 2 — Missing `_mock_settings` Fixture (Tests 3, 4)

### Exact error

```
pydantic_core._pydantic_core.ValidationError: 9 validation errors for Settings
supabase_url — Field required
supabase_anon_key — Field required
supabase_service_role_key — Field required
supabase_jwt_secret — Field required
openai_api_key — Field required
sarvam_api_key — Field required
heygen_api_key — Field required
langfuse_public_key — Field required
langfuse_secret_key — Field required

app\core\pubsub.py:39: in _run_lesson_subscriber
    settings = get_settings()
               ^^^^^^^^^^^^^^
app\config.py:146: in get_settings
    return Settings()   ← pydantic-settings requires all 9 env vars
```

### Root cause

`_run_lesson_subscriber` in `apps/api/app/core/pubsub.py` calls `get_settings()` at line 39:

```python
async def _run_lesson_subscriber(manager: ConnectionManager) -> None:
    from app.config import get_settings  # lazy import
    settings = get_settings()            # ← line 39 — fails without mock
    redis_url = settings.redis_url
    ...
```

The test file `test_lesson_ready_pubsub.py` does NOT mock `get_settings`. When
`_run_lesson_subscriber` is called inside the test, `get_settings()` tries to construct
`Settings()` which requires all 9 environment variables. In the test environment (no `.env`
file, no CI secrets) this raises `pydantic_core.ValidationError`.

This is the same pattern that affected Dev 3's quiz tests — fixed by adding an `autouse`
fixture that patches `get_settings` before the function runs.

### Fix

Add a `_mock_settings` autouse fixture to `apps/api/tests/test_lesson_ready_pubsub.py`.

**Where to add it:** After the imports, before the helper functions, with `autouse=True`
so every test in the file receives the mock automatically.

```python
# Add near the top of test_lesson_ready_pubsub.py, after existing imports
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    """Prevent pydantic ValidationError — get_settings() needs all 9 env vars."""
    mock = MagicMock()
    mock.redis_url = "redis://localhost:6379"
    monkeypatch.setattr("app.core.pubsub.get_settings", lambda: mock)
```

**Patch target is `app.core.pubsub.get_settings`** — the lazy import inside
`_run_lesson_subscriber` does `from app.config import get_settings`, which resolves
to `app.config.get_settings`. But after the lazy import runs, `get_settings` lives
on the `pubsub` module's local namespace. Patching `app.core.pubsub.get_settings`
replaces it there before the function runs.

**Why `redis_url` specifically:** The mock must have `redis_url` because
`_run_lesson_subscriber` accesses `settings.redis_url` immediately after calling
`get_settings()`. With `MagicMock()`, any attribute access returns another `MagicMock`,
so you can also set it explicitly for clarity. Check `pubsub.py` for any other
`settings.*` accesses and add them to the mock if needed.

---

## 4. Apply Both Fixes

### File 1: `apps/api/app/modules/content/pipeline/__init__.py`

```python
from . import graph
```

### File 2: `apps/api/tests/test_lesson_ready_pubsub.py`

Add this after the existing imports section at the top of the file:

```python
from unittest.mock import MagicMock   # (may already be imported — check first)


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    """Prevent pydantic ValidationError — get_settings() needs all 9 env vars."""
    mock = MagicMock()
    mock.redis_url = "redis://localhost:6379"
    monkeypatch.setattr("app.core.pubsub.get_settings", lambda: mock)
```

---

## 5. How to Verify

```bash
cd apps/api

# Fix 1: pipeline __init__.py
echo "from . import graph" > app/modules/content/pipeline/__init__.py

# Fix 2: add _mock_settings to test file (edit manually — see section 4)

# Run the 5 failing tests
python -m pytest tests/test_lesson_ready_pubsub.py -v

# Expected after both fixes:
# PASSED tests/test_lesson_ready_pubsub.py::test_publish_channel_uses_session_id
# PASSED tests/test_lesson_ready_pubsub.py::test_publish_message_has_correct_ws_shape
# PASSED tests/test_lesson_ready_pubsub.py::test_subscriber_forwards_pmessage_to_manager
# PASSED tests/test_lesson_ready_pubsub.py::test_subscriber_handles_malformed_json
# PASSED tests/test_lesson_ready_pubsub.py::test_routing_reaches_correct_client_when_session_id_differs
# 5 passed

# Full unit suite — confirm no regressions
python -m pytest -m unit tests/ -v
```

**Important:** If you only apply Fix 1 (without Fix 2), tests 1, 2, 5 will pass but tests 3, 4
will still fail with the `ValidationError`. Both fixes are required to get all 5 passing.

---

## 6. Why These Failures Exist

The `fix/sprint1-arq-lesson-ready-pubsub` PR (merged as commit `697f08d`) added:
- `app/core/pubsub.py` with `_run_lesson_subscriber`
- `apps/api/workers/jobs/content_pipeline.py` with Redis publish logic
- `tests/test_lesson_ready_pubsub.py` with all 5 tests

Two things were not done in that PR:
1. `pipeline/__init__.py` was not updated to expose `graph` (needed by tests 1, 2, 5's patch target)
2. No `_mock_settings` fixture was added (needed by tests 3, 4 since `pubsub.py` calls `get_settings()`)

---

## 7. Sprint Impact

| State | Failing count | Root cause |
|-------|---------------|------------|
| Before Fix 1 only | 5 fail | `__init__.py` empty |
| After Fix 1 only | 3 fail (tests 3, 4 still fail) | `get_settings()` unmocked |
| After Fix 1 + Fix 2 | 0 fail — 5 pass | Both resolved |

---

## 8. Combined Impact (Dev 1 + Dev 4)

Once both Dev 1 and Dev 4 apply their fixes:

| Before | After |
|--------|-------|
| 7 failing (5 pubsub + 2 websocket) | 0 failing |
| Baseline green count lower | Full green baseline restored |

Both fixes are independent — apply in either order. Dev 4's fix is one line in
`tutor/state_machine/__init__.py` (see `docs/dev4-websocket-test-fix-handoff.md`).

---

## 9. Suggested Branch

```bash
git checkout main
git checkout -b fix/pipeline-pubsub-test-fixes

# Fix 1
echo "from . import graph" > apps/api/app/modules/content/pipeline/__init__.py

# Fix 2 — add _mock_settings fixture to test file (edit manually)

git add apps/api/app/modules/content/pipeline/__init__.py
git add apps/api/tests/test_lesson_ready_pubsub.py
git commit -m "fix(dev1): expose pipeline.graph in __init__ + mock settings in pubsub tests"
git push origin fix/pipeline-pubsub-test-fixes
# Open PR → main
```

---

## 10. Quick Reference — Both Fixes

```python
# Fix 1: apps/api/app/modules/content/pipeline/__init__.py
from . import graph

# Fix 2: apps/api/tests/test_lesson_ready_pubsub.py — add this fixture
@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    mock = MagicMock()
    mock.redis_url = "redis://localhost:6379"
    monkeypatch.setattr("app.core.pubsub.get_settings", lambda: mock)
```
