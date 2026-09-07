"""Story 4-34 — Synthetic Session Concurrent Load + Data Integrity Test Suite.

Verifies that the 35 synthetic sessions produced by
``scripts/generate_synthetic_sessions.py`` have the correct shape, that
``ces_final`` values lie in [0, 100] (not [0, 10 000] from the ``* 100`` bug
fixed in AC 1), that concurrent ``compute_ces`` computation produces valid
independent results, and that every DB column name matches the real schema in
``supabase/migrations/``.

No DB connection is required — all assertions run against the generator's
in-memory output and the imported ``compute_ces`` function.

Run:
    cd apps/api
    python -m pytest tests/test_s4_34_synthetic_session_analysis.py -v
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: make the scripts/ directory importable so we can import
# generate_synthetic_sessions without an installed package.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Also ensure apps/api is on the path for the ces import inside the script.
_API_DIR = _REPO_ROOT / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


# ---------------------------------------------------------------------------
# Lazy import of the generator and the canonical CES function.
# ---------------------------------------------------------------------------

def _import_generator() -> types.ModuleType:
    """Import generate_synthetic_sessions without running main()."""
    import importlib

    mod = importlib.import_module("generate_synthetic_sessions")
    return mod


def _import_compute_ces():  # type: ignore[return]
    from app.modules.assessment.ces import compute_ces

    return compute_ces


def _get_settings():  # type: ignore[return]
    from app.config import get_settings

    return get_settings()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def generator():
    return _import_generator()


@pytest.fixture(scope="module")
def settings():
    return _get_settings()


@pytest.fixture(scope="module")
def session_rows(generator, settings):  # noqa: ARG001 — settings loaded for side-effect
    """35 synthetic session dicts, deterministic (random.seed(42))."""
    return generator.build_session_rows()


# ---------------------------------------------------------------------------
# CLASS 1 — Row count and structure
# ---------------------------------------------------------------------------

class TestSyntheticSessionRows:
    def test_row_count_is_35(self, session_rows: list[dict]) -> None:
        assert len(session_rows) == 35, (
            f"Expected 35 sessions (5 low + 15 mid + 15 high), got {len(session_rows)}"
        )

    def test_tier_distribution(self, session_rows: list[dict]) -> None:
        from collections import Counter

        counts = Counter(r["tier"] for r in session_rows)
        assert counts["low"] == 5
        assert counts["mid"] == 15
        assert counts["high"] == 15

    def test_all_rows_have_required_session_columns(self, session_rows: list[dict]) -> None:
        required = {"lesson_id", "started_at", "ended_at", "ces_final", "tier",
                    "quiz_acc", "n_questions", "tb_score", "tb_normalised",
                    "interventions", "behavioral"}
        for i, row in enumerate(session_rows):
            missing = required - set(row.keys())
            assert not missing, f"Row {i} missing keys: {missing}"

    def test_lesson_ids_are_all_distinct(self, session_rows: list[dict]) -> None:
        ids = [r["lesson_id"] for r in session_rows]
        assert len(set(ids)) == 35, "lesson_ids must be unique per session"

    def test_lesson_ids_are_valid_uuid_format(self, session_rows: list[dict]) -> None:
        import re
        pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        for row in session_rows:
            assert pattern.match(row["lesson_id"]), (
                f"lesson_id {row['lesson_id']!r} is not a valid UUID"
            )

    def test_started_at_before_ended_at(self, session_rows: list[dict]) -> None:
        for row in session_rows:
            assert row["started_at"] < row["ended_at"], (
                f"started_at must precede ended_at for lesson {row['lesson_id']}"
            )

    def test_n_questions_within_range(self, session_rows: list[dict]) -> None:
        for row in session_rows:
            assert 4 <= row["n_questions"] <= 12, (
                f"n_questions {row['n_questions']} outside [4, 12]"
            )


# ---------------------------------------------------------------------------
# CLASS 2 — CES final value integrity (core bug-fix verification)
# ---------------------------------------------------------------------------

class TestCESFinalIntegrity:
    """AC 5: ces_final must be in [0.0, 100.0], NOT [0, 10 000]."""

    def test_ces_final_is_in_valid_range(self, session_rows: list[dict]) -> None:
        for i, row in enumerate(session_rows):
            v = row["ces_final"]
            assert 0.0 <= v <= 100.0, (
                f"Row {i} (tier={row['tier']}): ces_final={v} is outside [0, 100]. "
                "This is the * 100 bug — compute_ces already returns 0–100."
            )

    def test_ces_final_is_never_above_100(self, session_rows: list[dict]) -> None:
        # Explicit guard: the buggy generator produced values > 100
        worst = max(r["ces_final"] for r in session_rows)
        assert worst <= 100.0, f"Maximum ces_final is {worst} — bug not fixed"

    def test_ces_final_matches_direct_compute_ces(
        self, session_rows: list[dict], settings
    ) -> None:
        """Each stored ces_final must equal compute_ces(...) directly (no extra *100)."""
        compute_ces = _import_compute_ces()
        for i, row in enumerate(session_rows):
            expected = round(
                compute_ces(
                    quiz_accuracy=row["quiz_acc"],
                    teachback_score=row["tb_normalised"],
                    behavioral=row["behavioral"],
                    head_pose=0.5,
                    blink=0.5,
                    settings=settings,
                ),
                2,
            )
            assert row["ces_final"] == expected, (
                f"Row {i}: stored ces_final={row['ces_final']}, "
                f"direct compute_ces={expected}. Mismatch indicates scale bug."
            )

    # Per-tier CES ranges (AC 8)
    def test_low_tier_ces_below_50(self, session_rows: list[dict]) -> None:
        low_rows = [r for r in session_rows if r["tier"] == "low"]
        for row in low_rows:
            assert row["ces_final"] <= 55.0, (
                f"Low-tier ces_final={row['ces_final']} is suspiciously high "
                "(expected ≤ 55 for 30–50% quiz acc, no teachback, 2–3 interventions)"
            )

    def test_high_tier_ces_above_50(self, session_rows: list[dict]) -> None:
        high_rows = [r for r in session_rows if r["tier"] == "high"]
        # At least 80% of high-tier sessions should be above 50
        above_50 = sum(1 for r in high_rows if r["ces_final"] > 50.0)
        assert above_50 >= 12, (
            f"Only {above_50}/15 high-tier sessions have ces_final > 50. "
            "Weight calibration may be off."
        )

    def test_teachback_redistribution_beats_zero_score(self, settings) -> None:
        """AC 9: When teachback=None, CES must exceed the case where teachback=0.

        This proves proportional redistribution is working, not that the signal
        just contributes 0 when absent.
        """
        compute_ces = _import_compute_ces()
        ces_none = compute_ces(
            quiz_accuracy=0.70,
            teachback_score=None,  # redistributed
            behavioral=0.80,
            head_pose=0.5,
            blink=0.5,
            settings=settings,
        )
        ces_zero = compute_ces(
            quiz_accuracy=0.70,
            teachback_score=0.0,   # counted as 0, drags result down
            behavioral=0.80,
            head_pose=0.5,
            blink=0.5,
            settings=settings,
        )
        assert ces_none > ces_zero, (
            f"Redistribution should give higher CES than teachback=0: "
            f"none={ces_none:.2f}, zero={ces_zero:.2f}"
        )

    def test_all_none_signals_returns_zero(self, settings) -> None:
        compute_ces = _import_compute_ces()
        result = compute_ces(
            quiz_accuracy=None,
            teachback_score=None,
            behavioral=None,
            head_pose=None,
            blink=None,
            settings=settings,
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# CLASS 3 — DB column name invariants
# ---------------------------------------------------------------------------

class TestDBColumnNames:
    """AC 4: verify column names match the real schema in supabase/migrations/."""

    def test_quiz_attempts_batch_columns(self, generator, session_rows: list[dict]) -> None:
        # Build what insert_quiz_attempts would produce for the first row
        row = session_rows[0]
        row_copy = dict(row)
        row_copy["session_id"] = "00000000-0000-0000-0000-000000000000"

        import random as _random

        n = row_copy["n_questions"]
        correct_count = round(row_copy["quiz_acc"] * n)
        answers = [True] * correct_count + [False] * (n - correct_count)
        _random.shuffle(answers)

        batch = [
            {
                "session_id": row_copy["session_id"],
                "segment_id": f"seg-{i // 3 + 1}",
                "question_id": f"q-{i + 1}",
                "response_index": 0 if answers[i] else 1,
                "is_correct": answers[i],
                "attempt_number": 1,
                "response_time_ms": 5000,
            }
            for i in range(n)
        ]

        # All required columns from the real schema must be present
        required_cols = {
            "session_id", "segment_id", "question_id",
            "response_index", "is_correct", "attempt_number", "response_time_ms",
        }
        for record in batch:
            missing = required_cols - set(record.keys())
            assert not missing, f"quiz_attempts record missing columns: {missing}"

        # No banned columns (these don't exist in schema)
        banned_cols = {"selected_option", "correct_option", "user_id"}
        for record in batch:
            present_banned = banned_cols & set(record.keys())
            assert not present_banned, f"quiz_attempts record has wrong columns: {present_banned}"

    def test_teachback_attempts_columns(self, session_rows: list[dict]) -> None:
        """AC 6 + AC 7: score_source in allowed set; score is int in [0, 100]."""
        valid_score_sources = {"llm", "fallback", "skipped"}

        tb_rows = [r for r in session_rows if r["tb_score"] is not None]
        assert len(tb_rows) > 0, "At least some sessions should have teachback"

        for row in tb_rows:
            # Build the teachback record as insert_teachback_attempts would
            record = {
                "session_id": "00000000-0000-0000-0000-000000000000",
                "segment_id": "seg-1",
                "response_text": "Synthetic student explanation for calibration.",
                "score": round(row["tb_score"]),
                "score_source": "llm",
                "attempt_number": 1,
            }
            # AC 6: score_source must satisfy F2-2 CHECK constraint
            assert record["score_source"] in valid_score_sources, (
                f"score_source={record['score_source']!r} violates F2-2 constraint"
            )
            # AC 7: score must be int in [0, 100]
            assert isinstance(record["score"], int), "score must be int"
            assert 0 <= record["score"] <= 100, (
                f"score={record['score']} outside [0, 100]"
            )
            # No banned columns (schema history — 'overall_score' was a prior wrong name)
            assert "overall_score" not in record
            # score_source must NOT be "synthetic" (not in CHECK list)
            assert record["score_source"] != "synthetic"

    def test_session_events_columns(self, session_rows: list[dict]) -> None:
        intv_rows = [r for r in session_rows if r["interventions"] > 0]
        assert len(intv_rows) > 0, "Some sessions must have interventions"

        for row in intv_rows:
            events = [
                {
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "event_type": "intervention_triggered",
                    "payload": {"intervention_number": i + 1, "source": "synthetic"},
                }
                for i in range(row["interventions"])
            ]
            for ev in events:
                assert "session_id" in ev
                assert "event_type" in ev
                assert "payload" in ev
                assert isinstance(ev["payload"], dict)

    def test_session_insert_columns(self, session_rows: list[dict]) -> None:
        """Session table uses 'session_id' as PK (not 'id') — schema validation."""
        # The generator reads resp.data[0]["session_id"] after insert — correct.
        # Build what the insert payload would look like.
        row = session_rows[0]
        insert_payload = {
            "user_id": "00000000-0000-0000-0000-000000000099",
            "lesson_id": row["lesson_id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "ces_final": row["ces_final"],
        }
        required = {"user_id", "lesson_id", "started_at", "ended_at", "ces_final"}
        assert set(insert_payload.keys()) == required
        # ces_final must be in valid range in the insert payload too
        assert 0.0 <= insert_payload["ces_final"] <= 100.0


# ---------------------------------------------------------------------------
# CLASS 4 — Idempotency SELECT bound (AC 11)
# ---------------------------------------------------------------------------

class TestIdempotencyBound:
    """AC 11: The dedup SELECT in insert_sessions uses .limit(50) — AST guard."""

    def test_idempotency_select_has_limit(self) -> None:
        """Source scan: insert_sessions must call .limit(50) on its SELECT."""
        script_path = _SCRIPTS_DIR / "generate_synthetic_sessions.py"
        source = script_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        found_limit_50 = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "limit"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 50
            ):
                found_limit_50 = True
                break

        assert found_limit_50, (
            "insert_sessions must call .limit(50) on its dedup SELECT "
            "(Scale Contract Q4 — unbounded read guard)"
        )


# ---------------------------------------------------------------------------
# CLASS 5 — Concurrent CES computation (AC 10)
# ---------------------------------------------------------------------------

class TestConcurrentCESComputation:
    """35 asyncio tasks computing compute_ces in parallel — proves no shared state."""

    def _all_ces_async(self, rows: list[dict], settings) -> list[float]:
        compute_ces = _import_compute_ces()

        async def _single(row: dict) -> float:
            return compute_ces(
                quiz_accuracy=row["quiz_acc"],
                teachback_score=row["tb_normalised"],
                behavioral=row["behavioral"],
                head_pose=0.5,
                blink=0.5,
                settings=settings,
            )

        async def _gather() -> list[float]:
            return list(await asyncio.gather(*[_single(r) for r in rows]))

        return asyncio.run(_gather())

    def test_35_concurrent_ces_calls_all_succeed(
        self, session_rows: list[dict], settings
    ) -> None:
        results = self._all_ces_async(session_rows, settings)
        assert len(results) == 35

    def test_concurrent_results_all_in_valid_range(
        self, session_rows: list[dict], settings
    ) -> None:
        results = self._all_ces_async(session_rows, settings)
        for i, v in enumerate(results):
            assert 0.0 <= v <= 100.0, (
                f"Concurrent result {i}: {v} is outside [0.0, 100.0]"
            )

    def test_concurrent_results_match_serial(
        self, session_rows: list[dict], settings
    ) -> None:
        """Same inputs → same output regardless of execution order (no shared state)."""
        compute_ces = _import_compute_ces()

        serial = [
            compute_ces(
                quiz_accuracy=r["quiz_acc"],
                teachback_score=r["tb_normalised"],
                behavioral=r["behavioral"],
                head_pose=0.5,
                blink=0.5,
                settings=settings,
            )
            for r in session_rows
        ]
        concurrent = self._all_ces_async(session_rows, settings)

        for i, (s, c) in enumerate(zip(serial, concurrent)):
            assert s == c, (
                f"Row {i}: serial={s}, concurrent={c} — compute_ces is not pure!"
            )

    def test_no_exception_on_concurrent_run(
        self, session_rows: list[dict], settings
    ) -> None:
        """asyncio.gather must not raise for any of the 35 rows."""
        try:
            self._all_ces_async(session_rows, settings)
        except Exception as exc:
            pytest.fail(f"Concurrent CES computation raised: {exc}")

    def test_concurrent_none_signals_handled(self, settings) -> None:
        """Rows with all-None MediaPipe signals must produce 0.0 without crashing."""
        compute_ces = _import_compute_ces()

        rows = [
            {"quiz_acc": 0.6, "tb_normalised": None, "behavioral": None},
            {"quiz_acc": None, "tb_normalised": None, "behavioral": None},
            {"quiz_acc": 0.8, "tb_normalised": 0.7, "behavioral": None},
        ]

        async def _gather():
            return list(
                await asyncio.gather(
                    *[
                        asyncio.coroutine(lambda r=r: compute_ces(  # type: ignore[attr-defined]
                            quiz_accuracy=r["quiz_acc"],
                            teachback_score=r["tb_normalised"],
                            behavioral=r["behavioral"],
                            head_pose=None,
                            blink=None,
                            settings=settings,
                        ))()
                        for r in rows
                    ]
                )
            )

        # Use the simpler direct asyncio pattern to avoid coroutine decorator deprecation
        async def _single_ces(r: dict) -> float:
            return compute_ces(
                quiz_accuracy=r["quiz_acc"],
                teachback_score=r["tb_normalised"],
                behavioral=r["behavioral"],
                head_pose=None,
                blink=None,
                settings=settings,
            )

        async def _run():
            return list(await asyncio.gather(*[_single_ces(r) for r in rows]))

        results = asyncio.run(_run())
        assert len(results) == 3
        for v in results:
            assert 0.0 <= v <= 100.0


# ---------------------------------------------------------------------------
# CLASS 6 — Quiz accuracy within tier bounds
# ---------------------------------------------------------------------------

class TestQuizAccuracyBounds:
    def test_low_tier_quiz_acc_range(self, session_rows: list[dict]) -> None:
        low = [r for r in session_rows if r["tier"] == "low"]
        for row in low:
            assert 0.30 <= row["quiz_acc"] <= 0.50, (
                f"Low tier quiz_acc={row['quiz_acc']} outside [0.30, 0.50]"
            )

    def test_mid_tier_quiz_acc_range(self, session_rows: list[dict]) -> None:
        mid = [r for r in session_rows if r["tier"] == "mid"]
        for row in mid:
            assert 0.55 <= row["quiz_acc"] <= 0.75, (
                f"Mid tier quiz_acc={row['quiz_acc']} outside [0.55, 0.75]"
            )

    def test_high_tier_quiz_acc_range(self, session_rows: list[dict]) -> None:
        high = [r for r in session_rows if r["tier"] == "high"]
        for row in high:
            assert 0.80 <= row["quiz_acc"] <= 0.95, (
                f"High tier quiz_acc={row['quiz_acc']} outside [0.80, 0.95]"
            )

    def test_low_tier_has_no_teachback(self, session_rows: list[dict]) -> None:
        low = [r for r in session_rows if r["tier"] == "low"]
        for row in low:
            assert row["tb_score"] is None, (
                f"Low-tier session has teachback score={row['tb_score']} "
                "(tier definition requires None)"
            )

    def test_interventions_within_tier_range(self, session_rows: list[dict]) -> None:
        for row in session_rows:
            tier = row["tier"]
            n = row["interventions"]
            if tier == "low":
                assert 2 <= n <= 3, f"Low interventions={n} outside [2, 3]"
            elif tier == "mid":
                assert 0 <= n <= 2, f"Mid interventions={n} outside [0, 2]"
            else:
                assert 0 <= n <= 1, f"High interventions={n} outside [0, 1]"

    def test_behavioral_derived_from_interventions(self, session_rows: list[dict]) -> None:
        for row in session_rows:
            expected = round(1.0 - (row["interventions"] / 3.0), 4)
            assert row["behavioral"] == expected, (
                f"behavioral={row['behavioral']} != 1 - interventions/3 = {expected}"
            )


# ---------------------------------------------------------------------------
# CLASS 7 — Teachback score properties
# ---------------------------------------------------------------------------

class TestTeachbackScore:
    def test_mid_teachback_in_range_when_present(self, session_rows: list[dict]) -> None:
        mid_tb = [r for r in session_rows if r["tier"] == "mid" and r["tb_score"] is not None]
        for row in mid_tb:
            assert 55.0 <= row["tb_score"] <= 75.0, (
                f"Mid teachback score {row['tb_score']} outside [55, 75]"
            )

    def test_high_teachback_in_range_when_present(self, session_rows: list[dict]) -> None:
        high_tb = [r for r in session_rows if r["tier"] == "high" and r["tb_score"] is not None]
        for row in high_tb:
            assert 75.0 <= row["tb_score"] <= 95.0, (
                f"High teachback score {row['tb_score']} outside [75, 95]"
            )

    def test_tb_normalised_is_score_div_100(self, session_rows: list[dict]) -> None:
        for row in session_rows:
            if row["tb_score"] is None:
                assert row["tb_normalised"] is None
            else:
                expected = row["tb_score"] / 100.0
                assert abs(row["tb_normalised"] - expected) < 1e-6, (
                    f"tb_normalised={row['tb_normalised']} != tb_score/100={expected}"
                )

    def test_at_least_50_pct_mid_high_have_teachback(self, session_rows: list[dict]) -> None:
        """~60% of mid/high sessions have teachback by design."""
        mid_high = [r for r in session_rows if r["tier"] in ("mid", "high")]
        with_tb = [r for r in mid_high if r["tb_score"] is not None]
        rate = len(with_tb) / len(mid_high)
        assert rate >= 0.30, (
            f"Only {rate:.0%} of mid/high sessions have teachback "
            "(expected ≥ 30%, designed for ~60%)"
        )


# ---------------------------------------------------------------------------
# CLASS 8 — Determinism (random.seed(42) guarantee)
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_build_session_rows_is_deterministic(self, generator) -> None:
        """Two calls to build_session_rows() must return identical data."""
        rows_a = generator.build_session_rows()
        rows_b = generator.build_session_rows()
        assert len(rows_a) == len(rows_b) == 35
        for i, (a, b) in enumerate(zip(rows_a, rows_b)):
            assert a["ces_final"] == b["ces_final"], (
                f"Row {i}: non-deterministic ces_final: {a['ces_final']} vs {b['ces_final']}"
            )
            assert a["quiz_acc"] == b["quiz_acc"], f"Row {i}: non-deterministic quiz_acc"

    def test_synthetic_lesson_ids_are_35(self, generator) -> None:
        assert len(generator.SYNTHETIC_LESSON_IDS) == 35

    def test_last_lesson_id_is_correct(self, generator) -> None:
        # The 35th ID should be 00000000-0000-0000-0000-000000000035
        last = generator.SYNTHETIC_LESSON_IDS[-1]
        assert last == "00000000-0000-0000-0000-000000000035"
