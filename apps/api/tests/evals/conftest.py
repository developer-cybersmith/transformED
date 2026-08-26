"""
Story 2-14/S2-14 AC-8: exclude the `live_eval`-marked test from default
pytest collection without touching the repo-wide `addopts` in pyproject.toml.

2026-07-17 review finding (Acceptance Auditor): the first version of this
story wired `-m "not live_eval"` directly into `pyproject.toml`'s global
`addopts`, which changes the default `pytest` invocation for every
developer/CI run in the whole repo — exactly the action Task 4.3 flagged as
needing team confirmation before doing, which was never obtained. Reverted
that global change in favor of this scoped, `tests/evals/`-local
`conftest.py` — it auto-skips `live_eval` tests by default and only runs
them when `--run-live-eval` is explicitly passed, without altering how any
other test in the repo is selected.

D126 (2026-08-20): the FIRST real `--run-live-eval` attempt against this
gate failed every one of the 20 PDFs in <1s with `[Errno 61] Connection
refused` — before spending any real API money, but before ever reaching a
provider either. Root cause: `tests/conftest.py`'s module-level
`os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")` (and 9
other stub credentials) runs at collection time for EVERY pytest
invocation in this repo, including this one — and pydantic-settings
prioritizes `os.environ` over `.env`, so the real credentials in `.env`
were silently never used. This is the documented, "official" way to run
this gate (this file's own module docstring above, and `test_live_run.py`'s
docstring: `pytest tests/evals/test_live_run.py -v --run-live-eval`) — the
gate was unusable as documented since the stub was introduced, previously
worked around by invoking `run_all_evals()` as a bare script instead of
through pytest, which never fixed the actual documented entry point.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-eval",
        action="store_true",
        default=False,
        help=(
            "Run the S2-14 eval harness live test "
            "(hits real OpenAI/Sarvam/Azure/Supabase, costs real money)."
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-eval"):
        return
    skip_live = pytest.mark.skip(
        reason="live_eval test skipped by default — pass --run-live-eval to run it"
    )
    for item in items:
        if "live_eval" in item.keywords:
            item.add_marker(skip_live)


def pytest_configure(config: pytest.Config) -> None:
    """D126: undo `tests/conftest.py`'s stub-credential poisoning for a real
    live-eval run.

    Runs after every conftest.py's module-level code (the stubs are already
    in `os.environ` by this point) and before any test function executes —
    `get_settings()` is called lazily inside `run_eval`'s own function body,
    never at collection time, so restoring the real values here is not too
    late. Reads `apps/api/.env` directly (the same file `Settings.env_file`
    names) rather than relying on CWD, and OVERWRITES `os.environ` (not
    `setdefault`) — the stubs are already present and must be replaced, not
    deferred to.
    """
    if not config.getoption("--run-live-eval"):
        return
    env_path = Path(__file__).parent.parent.parent / ".env"
    real_values = dotenv_values(env_path)
    if not real_values:
        raise RuntimeError(
            f"--run-live-eval requires real credentials in {env_path}, but it is "
            "missing or empty — refusing to run the gate against tests/conftest.py's "
            "stub values, which would silently fail every PDF (see D126)."
        )
    for key, value in real_values.items():
        if value is not None:
            os.environ[key] = value
