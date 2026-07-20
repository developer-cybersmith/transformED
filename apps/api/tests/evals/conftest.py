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
"""

from __future__ import annotations

import pytest


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
