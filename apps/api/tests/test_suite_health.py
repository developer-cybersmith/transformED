"""
Suite health — fast unit marker sentinel.

Purpose: ensure `pytest -m unit` always collects at least one test and
exits 0 rather than exit-code 5 ("no tests collected"). This file never
imports external dependencies.
"""

import pytest


@pytest.mark.unit
def test_unit_marker_wired() -> None:
    """pytest -m unit must exit 0; this sentinel guarantees a test is collected."""
    assert True
