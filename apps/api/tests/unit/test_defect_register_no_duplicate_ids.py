"""Guard: every D-entry in docs/DEFECT-REGISTER.md has a unique ID.

The register has a documented exception for D64 (intentional dual-entry per the
fourth-occurrence banner and the reconcile-by-note at D64's own collision site).
Every other D-number must appear exactly once.

This test catches collisions introduced when parallel branches allocate the same
ID without first re-reading main's highest-allocated number — the exact class of
defect named by the register's own banner, and the reason Story 5-13 exists.
"""

import re
from collections import Counter
from pathlib import Path

import pytest

_REGISTER_PATH = Path(__file__).parent.parent.parent.parent.parent / "docs" / "DEFECT-REGISTER.md"

# D64 is a documented intentional dual-entry (see the ⚠️ fourth-occurrence banner
# at the top of DEFECT-REGISTER.md).  All other IDs must appear exactly once.
_PERMITTED_DUPLICATES: frozenset[int] = frozenset({64})

_ID_PATTERN = re.compile(
    r"""
    (?:
        ^\#\#\s+D(\d+)\b           # heading format: ## D123
        |
        \|\s+\*\*D(\d+)\*\*\s+\|  # table format:   | **D123** |
    )
    """,
    re.VERBOSE | re.MULTILINE,
)


def _extract_ids(text: str) -> list[int]:
    """Return every D-number found in the register text."""
    ids = []
    for m in _ID_PATTERN.finditer(text):
        raw = m.group(1) or m.group(2)
        ids.append(int(raw))
    return ids


@pytest.mark.unit
def test_defect_register_exists() -> None:
    assert _REGISTER_PATH.exists(), f"DEFECT-REGISTER.md not found at {_REGISTER_PATH}"


@pytest.mark.unit
def test_defect_register_no_duplicate_ids() -> None:
    """AC1: every D-number appears at most once (D64 excepted)."""
    text = _REGISTER_PATH.read_text(encoding="utf-8")
    ids = _extract_ids(text)
    counts = Counter(ids)

    duplicates = {
        d_id: count
        for d_id, count in counts.items()
        if count > 1 and d_id not in _PERMITTED_DUPLICATES
    }

    assert not duplicates, (
        "DEFECT-REGISTER.md contains duplicate D-entry IDs (Story 5-13 must fix):\n"
        + "\n".join(
            f"  D{d_id} appears {count} times" for d_id, count in sorted(duplicates.items())
        )
    )


@pytest.mark.unit
def test_defect_register_d64_permitted_duplicate() -> None:
    """D64 is the only permitted dual-entry; assert it still exists twice.

    If D64 is ever renumbered (resolving the intentional dual-entry), update
    _PERMITTED_DUPLICATES above too.
    """
    text = _REGISTER_PATH.read_text(encoding="utf-8")
    ids = _extract_ids(text)
    d64_count = ids.count(64)
    assert d64_count >= 1, "D64 has been removed from the register entirely — update this guard."
    # The convention allows D64 to appear twice; don't assert == 2 since a future
    # reconciliation may legitimately drop one copy.
