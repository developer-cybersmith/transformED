"""Unit tests for S4-32 CES weight verification script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def vw_mod() -> ModuleType:
    return _load_script("verify_ces_weights")


class TestTargets:
    def test_targets_sum_to_one(self, vw_mod: ModuleType) -> None:
        total = sum(vw_mod.TARGETS.values())
        assert abs(total - 1.0) < 1e-9

    def test_targets_have_five_weights(self, vw_mod: ModuleType) -> None:
        assert len(vw_mod.TARGETS) == 5

    def test_quiz_weight_is_040(self, vw_mod: ModuleType) -> None:
        assert abs(vw_mod.TARGETS["ces_weight_quiz"] - 0.40) < 1e-9

    def test_behavioral_weight_is_015(self, vw_mod: ModuleType) -> None:
        assert abs(vw_mod.TARGETS["ces_weight_behavioral"] - 0.15) < 1e-9


class TestVerifyWeights:
    def test_all_match_returns_true_no_issues(self, vw_mod: ModuleType) -> None:
        actual = dict(vw_mod.TARGETS)  # perfect match
        ok, issues = vw_mod.verify_weights(actual)
        assert ok is True
        assert issues == []

    def test_mismatch_returns_false_with_issue(self, vw_mod: ModuleType) -> None:
        actual = dict(vw_mod.TARGETS)
        actual["ces_weight_quiz"] = 0.35  # old value
        ok, issues = vw_mod.verify_weights(actual)
        assert ok is False
        assert any("ces_weight_quiz" in msg for msg in issues)

    def test_none_value_is_not_mismatch_flagged_as_error(self, vw_mod: ModuleType) -> None:
        actual = dict(vw_mod.TARGETS)
        actual["ces_weight_quiz"] = None  # not set in env
        ok, issues = vw_mod.verify_weights(actual)
        # None means "using default" — not an error for the verify function
        assert any("NOT SET" in msg for msg in issues)
        # ok depends on implementation — None is reported as a note, not a hard mismatch
        # but our verify_weights counts it as an issue (non-empty issues list)
        assert len(issues) == 1  # one issue reported (the None)


class TestReadWeightsFromEnv:
    def test_reads_env_vars_correctly(self, vw_mod: ModuleType) -> None:
        env = {
            "CES_WEIGHT_QUIZ": "0.40",
            "CES_WEIGHT_TEACHBACK": "0.25",
            "CES_WEIGHT_BEHAVIORAL": "0.15",
            "CES_WEIGHT_HEAD_POSE": "0.13",
            "CES_WEIGHT_BLINK": "0.07",
        }
        with patch.dict("os.environ", env, clear=False):
            result = vw_mod.read_weights_from_env()
        assert abs(result["ces_weight_quiz"] - 0.40) < 1e-9
        assert abs(result["ces_weight_behavioral"] - 0.15) < 1e-9

    def test_missing_env_var_returns_none(self, vw_mod: ModuleType) -> None:
        # Patch so no CES_ vars exist
        with patch.dict("os.environ", {}, clear=True):
            result = vw_mod.read_weights_from_env()
        assert all(v is None for v in result.values())

    def test_bad_env_var_value_returns_none(self, vw_mod: ModuleType) -> None:
        env = {"CES_WEIGHT_QUIZ": "not-a-float"}
        with patch.dict("os.environ", env):
            result = vw_mod.read_weights_from_env()
        assert result["ces_weight_quiz"] is None
