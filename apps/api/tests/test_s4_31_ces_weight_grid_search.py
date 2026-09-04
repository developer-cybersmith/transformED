"""
Unit tests for S4-31 CES weight grid search script.

No network, no Supabase, no running API required.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

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
def gs_mod() -> ModuleType:
    return _load_script("ces_weight_grid_search")


# ---------------------------------------------------------------------------
# Weight combination invariants
# ---------------------------------------------------------------------------

class TestWeightCombinations:
    def test_all_combinations_sum_to_1(self, gs_mod: ModuleType) -> None:
        for combo in gs_mod.WEIGHT_COMBINATIONS:
            assert abs(sum(combo) - 1.0) < 1e-9, f"Combo {combo} sums to {sum(combo)}"

    def test_exactly_5_combinations(self, gs_mod: ModuleType) -> None:
        assert len(gs_mod.WEIGHT_COMBINATIONS) == 5

    def test_all_weights_non_negative(self, gs_mod: ModuleType) -> None:
        for combo in gs_mod.WEIGHT_COMBINATIONS:
            assert all(w >= 0.0 for w in combo), f"Negative weight in {combo}"


# ---------------------------------------------------------------------------
# pearson_r
# ---------------------------------------------------------------------------

class TestPearsonR:
    def test_perfect_positive_correlation(self, gs_mod: ModuleType) -> None:
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = gs_mod.pearson_r(xs, ys)
        assert abs(r - 1.0) < 1e-9

    def test_perfect_negative_correlation(self, gs_mod: ModuleType) -> None:
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [10.0, 8.0, 6.0, 4.0, 2.0]
        r = gs_mod.pearson_r(xs, ys)
        assert abs(r - (-1.0)) < 1e-9

    def test_single_element_returns_zero(self, gs_mod: ModuleType) -> None:
        assert gs_mod.pearson_r([1.0], [2.0]) == 0.0

    def test_constant_series_returns_zero(self, gs_mod: ModuleType) -> None:
        # constant y → zero correlation (statistics.correlation raises StatisticsError)
        r = gs_mod.pearson_r([1.0, 2.0, 3.0], [5.0, 5.0, 5.0])
        assert r == 0.0


# ---------------------------------------------------------------------------
# compute_ces_row
# ---------------------------------------------------------------------------

class TestComputeCesRow:
    _weights = (0.35, 0.25, 0.20, 0.12, 0.08)  # baseline

    def _row(self, quiz_pct: float, teachback_avg=None, interventions: int = 0) -> dict:
        return {
            "quiz_accuracy_pct": quiz_pct,
            "teachback_avg": teachback_avg,
            "interventions": interventions,
        }

    def test_full_signals_range_0_100(self, gs_mod: ModuleType) -> None:
        result = gs_mod.compute_ces_row(self._row(70.0, teachback_avg=80.0), self._weights)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_missing_quiz_returns_none(self, gs_mod: ModuleType) -> None:
        row = {"quiz_accuracy_pct": "bad", "teachback_avg": None, "interventions": 0}
        assert gs_mod.compute_ces_row(row, self._weights) is None

    def test_no_teachback_redistributes_weight(self, gs_mod: ModuleType) -> None:
        row_with = self._row(70.0, teachback_avg=70.0)
        row_without = self._row(70.0, teachback_avg=None)
        ces_with = gs_mod.compute_ces_row(row_with, self._weights)
        ces_without = gs_mod.compute_ces_row(row_without, self._weights)
        # Without teachback the weight redistributes — result is different
        assert ces_with is not None
        assert ces_without is not None
        assert ces_with != ces_without

    def test_zero_quiz_gives_low_ces(self, gs_mod: ModuleType) -> None:
        result = gs_mod.compute_ces_row(self._row(0.0, teachback_avg=0.0, interventions=3), self._weights)
        assert result is not None
        assert result < 50.0

    def test_perfect_quiz_gives_high_ces(self, gs_mod: ModuleType) -> None:
        result = gs_mod.compute_ces_row(self._row(100.0, teachback_avg=100.0, interventions=0), self._weights)
        assert result is not None
        assert result > 60.0


# ---------------------------------------------------------------------------
# run_grid_search — smoke test with synthetic data
# ---------------------------------------------------------------------------

class TestRunGridSearch:
    def _make_rows(self, n: int = 10) -> list[dict]:
        """Generate n sessions with varying quiz accuracy."""
        rows = []
        for i in range(n):
            rows.append({
                "quiz_accuracy_pct": 50.0 + i * 4.0,
                "teachback_avg": None,
                "interventions": i % 3,
                "ces_final": 40.0 + i * 3.0,
            })
        return rows

    def test_returns_best_combo_and_r(self, gs_mod: ModuleType) -> None:
        rows = self._make_rows(10)
        best_combo, best_r, results = gs_mod.run_grid_search(rows)
        assert len(best_combo) == 5
        assert isinstance(best_r, float)
        assert len(results) == 5

    def test_insufficient_data_exits(self, gs_mod: ModuleType) -> None:
        rows = self._make_rows(3)  # below _MIN_USABLE=5
        with pytest.raises(SystemExit) as exc_info:
            gs_mod.run_grid_search(rows)
        assert exc_info.value.code == 1

    def test_results_contain_expected_keys(self, gs_mod: ModuleType) -> None:
        rows = self._make_rows(10)
        _, _, results = gs_mod.run_grid_search(rows)
        for r in results:
            assert "quiz" in r
            assert "pearson_r" in r
            assert "n_sessions" in r
            assert r["n_sessions"] == 10


# ---------------------------------------------------------------------------
# write_results_csv
# ---------------------------------------------------------------------------

class TestWriteResultsCsv:
    def test_csv_has_correct_columns(self, gs_mod: ModuleType, tmp_path) -> None:
        results = [
            {"quiz": 0.35, "teachback": 0.25, "behavioral": 0.20,
             "head_pose": 0.12, "blink": 0.08, "pearson_r": 0.72, "n_sessions": 20},
        ]
        out = str(tmp_path / "results.csv")
        gs_mod.write_results_csv(results, out)
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert "pearson_r" in rows[0]
        assert "quiz" in rows[0]
