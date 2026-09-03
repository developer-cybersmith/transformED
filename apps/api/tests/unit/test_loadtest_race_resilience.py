"""Regression test for the race-probe report-loss bug found on load-test
run #8 (2026-09-03): a `--scale full` run whose Phase A/B load completed
successfully still exited 1 and wrote NO report at all, because
`_list_all_chapter_ids` raised a bare `RuntimeError` on a 401 from the
Gate-7 probe's chapter-listing call, uncaught, all the way out of
`_main_async` — discarding valid Phase A/B data along with the probe
failure.

`tests.loadtest.report.build_report` is explicitly documented as doing "no
I/O and mak[ing] no HTTP calls" so it "can be unit-tested... with zero
network dependency" — this test exercises exactly that seam: the race-probe
dicts must be able to represent "the probe itself failed" as distinct from
"the probe ran and did not reproduce the race" or "the probe was skipped",
so a caller (`run.py`'s `_run_full`) can catch a probe exception and still
produce a report that says so, instead of losing everything.
"""

from __future__ import annotations

from tests.loadtest.report import _render_race


def test_render_race_skipped_when_probe_dict_is_empty() -> None:
    rendered = _render_race("D45 (chapter_id, tier) idempotency race", {})
    assert "SKIPPED" in rendered
    assert "FAILED" not in rendered


def test_render_race_not_reproduced_when_mitigation_held() -> None:
    probe = {"reproduced": False, "responses": [202, 200], "note": "mitigation held"}
    rendered = _render_race("D45 (chapter_id, tier) idempotency race", probe)
    assert "NOT reproduced" in rendered
    assert "FAILED" not in rendered


def test_render_race_reproduced_when_race_was_hit() -> None:
    probe = {"reproduced": True, "responses": [202, 202], "note": "double insert"}
    rendered = _render_race("D45 (chapter_id, tier) idempotency race", probe)
    assert "REPRODUCED" in rendered
    assert "NOT reproduced" not in rendered


def test_render_race_reports_failed_distinctly_from_skipped_or_not_reproduced() -> None:
    """The exact shape `_run_full` now produces when a probe raises: neither
    an empty dict (skipped) nor a `reproduced: False` result (mitigation
    held) — those two would silently read as "nothing to worry about",
    which is precisely what caused run #8's real Phase A/B data to be
    reported as if the probes had simply not reproduced anything, instead of
    surfacing that they never actually completed."""
    probe = {
        "reproduced": False,
        "error": "chapter list failed for book abc-123: 401 {'detail':'Token has expired'}",
    }
    rendered = _render_race("Gate 7 per-user concurrency oversubscription race", probe)
    assert "FAILED" in rendered
    assert "Token has expired" in rendered
    assert "SKIPPED" not in rendered
    assert "NOT reproduced" not in rendered
