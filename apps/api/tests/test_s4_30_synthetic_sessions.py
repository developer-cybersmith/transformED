"""
Unit tests for S4-30 synthetic session generator and calibration export scripts.

All network calls are mocked — no running API or Supabase required.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load scripts as modules without executing top-level side effects.
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def gen_mod() -> ModuleType:
    return _load_script("generate_test_sessions")


@pytest.fixture(scope="module")
def exp_mod() -> ModuleType:
    return _load_script("export_calibration_data")


# ---------------------------------------------------------------------------
# AC 1 tests — generator script
# ---------------------------------------------------------------------------


class TestQuizAccuracyRandomisation:
    """AC 1 / AC 5 — quiz answer randomisation respects accuracy rate."""

    def test_all_correct_when_rate_1(self, gen_mod: ModuleType) -> None:
        answers = gen_mod.build_quiz_answers(n_questions=10, accuracy=1.0, seed=0)
        assert all(a["is_correct"] for a in answers)

    def test_none_correct_when_rate_0(self, gen_mod: ModuleType) -> None:
        answers = gen_mod.build_quiz_answers(n_questions=10, accuracy=0.0, seed=0)
        assert not any(a["is_correct"] for a in answers)

    def test_approx_correct_at_0_7(self, gen_mod: ModuleType) -> None:
        answers = gen_mod.build_quiz_answers(n_questions=100, accuracy=0.7, seed=42)
        correct = sum(1 for a in answers if a["is_correct"])
        # With seed=42 and 100 items, should be close to 70 (±10 for randomness)
        assert 55 <= correct <= 85

    def test_answer_has_required_fields(self, gen_mod: ModuleType) -> None:
        answers = gen_mod.build_quiz_answers(n_questions=3, accuracy=0.5, seed=1)
        for a in answers:
            assert "question_id" in a
            assert "response_index" in a
            assert "response_time_ms" in a
            assert isinstance(a["response_time_ms"], int)
            assert a["response_time_ms"] >= 500  # AC 1: min floor 500ms

    def test_n_questions_bounds(self, gen_mod: ModuleType) -> None:
        with pytest.raises(ValueError, match="n_questions"):
            gen_mod.build_quiz_answers(n_questions=0, accuracy=0.5, seed=0)


class TestTeachbackStub:
    """AC 1 — teachback stub payload."""

    def test_stub_response_is_non_empty(self, gen_mod: ModuleType) -> None:
        payload = gen_mod.build_teachback_payload(segment_id="seg-1")
        assert payload["response_text"] and len(payload["response_text"]) > 10

    def test_stub_payload_has_required_fields(self, gen_mod: ModuleType) -> None:
        payload = gen_mod.build_teachback_payload(segment_id="seg-1")
        assert "segment_id" in payload
        assert "response_text" in payload
        assert "is_skip" in payload
        assert payload["is_skip"] is False

    def test_skip_payload(self, gen_mod: ModuleType) -> None:
        payload = gen_mod.build_teachback_payload(segment_id="seg-2", skip=True)
        assert payload["is_skip"] is True


class TestCsvOutputFormat:
    """AC 1 — CSV summary output format."""

    def test_csv_columns(self, gen_mod: ModuleType) -> None:
        buf = io.StringIO()
        rows = [
            {
                "session_id": "abc",
                "quiz_accuracy_pct": 70.0,
                "teachback_avg_score": 80.0,
                "ces_final": None,
                "n_quiz_attempts": 3,
                "n_teachback_attempts": 3,
            }
        ]
        gen_mod.write_summary_csv(rows, buf)
        buf.seek(0)
        reader = csv.DictReader(buf)
        headers = reader.fieldnames or []
        assert "session_id" in headers
        assert "quiz_accuracy_pct" in headers
        assert "teachback_avg_score" in headers
        assert "ces_final" in headers
        assert "n_quiz_attempts" in headers
        assert "n_teachback_attempts" in headers


class TestArgParserDefaults:
    """AC 1 — CLI arg defaults."""

    def test_default_n_sessions(self, gen_mod: ModuleType) -> None:
        parser = gen_mod.build_arg_parser()
        args = parser.parse_args(["--api-url", "http://localhost:8000", "--auth-token", "tok"])
        assert args.n_sessions == 20

    def test_default_segments(self, gen_mod: ModuleType) -> None:
        parser = gen_mod.build_arg_parser()
        args = parser.parse_args(["--api-url", "http://localhost:8000", "--auth-token", "tok"])
        assert args.segments_per_session == 3

    def test_default_quiz_accuracy(self, gen_mod: ModuleType) -> None:
        parser = gen_mod.build_arg_parser()
        args = parser.parse_args(["--api-url", "http://localhost:8000", "--auth-token", "tok"])
        assert args.quiz_accuracy == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# AC 2 tests — export script
# ---------------------------------------------------------------------------


class TestExportRowShape:
    """AC 2 — calibration export CSV row shape."""

    def test_export_row_has_all_columns(self, exp_mod: ModuleType) -> None:
        row = exp_mod.build_export_row(
            session={
                "id": "sess-1",
                "user_id": "user-1",
                "started_at": "2026-09-01T10:00:00Z",
                "ended_at": "2026-09-01T10:30:00Z",
                "ces_final": 62.5,
            },
            quiz_accuracy_pct=70.0,
            quiz_attempts=6,
            teachback_avg=78.0,
            teachback_attempts=2,
            interventions=2,
            tab_switches=2,
        )
        expected_cols = {
            "session_id",
            "user_id",
            "started_at",
            "ended_at",
            "ces_final",
            "quiz_accuracy_pct",
            "quiz_attempts",
            "teachback_avg",
            "teachback_attempts",
            "interventions",
            "tab_switches",
        }
        assert expected_cols == set(row.keys())

    def test_export_signals_capped_warning(self, exp_mod: ModuleType, capsys: Any) -> None:
        """AC 2 — signals_capped printed when limit hit."""
        exp_mod.maybe_warn_signals_capped(signals_capped=True, table="sessions", limit=10_000)
        captured = capsys.readouterr()
        assert "signals_capped" in captured.out or "WARN" in captured.out
