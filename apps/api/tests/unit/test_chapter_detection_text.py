"""Direct unit coverage for chapter_detection/text.py's D115/D116 additions.

title_present's `tail_window` and extract_subprocess's `tail_chars` are both
opt-in (default 0) precisely so every pre-existing caller is byte-identical --
these tests pin that default-off behaviour explicitly, then pin the opt-in
behaviour on its own, small, PDF-free inputs (binding rule 2).
"""

from __future__ import annotations

import pytest

from app.modules.content.chapter_detection.text import CONTENTS_HDR_RE, title_present


@pytest.mark.unit
def test_tail_window_defaults_to_off_and_is_byte_identical_to_the_old_behaviour() -> None:
    page = "body text " * 50 + "TARGET TITLE"
    # The title sits well past char 400 (the default `window`), tail_window
    # defaults to 0, so this must fail exactly as it always has.
    assert not title_present(page, "Target Title")


@pytest.mark.unit
def test_tail_window_finds_a_title_placed_after_the_window() -> None:
    page = "body text " * 50 + "TARGET TITLE"
    assert len(page) > 400
    assert title_present(page, "Target Title", tail_window=400)


@pytest.mark.unit
def test_tail_window_is_a_strict_superset_never_a_regression() -> None:
    """Widening the search can only turn a prior False into True -- confirms
    the monotonic argument the regression analysis rests on, on a real input
    rather than by inspection alone."""
    page = "Target Title appears right at the start.\n" + ("filler " * 200)
    assert title_present(page, "Target Title")  # already true at window default
    assert title_present(page, "Target Title", tail_window=400)  # stays true


@pytest.mark.unit
def test_tail_window_no_op_on_a_page_shorter_than_the_head_window() -> None:
    page = "short page with Target Title in it"
    assert len(page) < 400
    assert title_present(page, "Target Title") == title_present(
        page, "Target Title", tail_window=400
    )


@pytest.mark.unit
def test_tail_window_title_with_middle_chars_in_the_skipped_region_is_not_found() -> None:
    """Documents actual behaviour rather than assuming it: title_present's
    haystack is head+tail CONCATENATED, not the whole page -- a title with
    characters that fall strictly inside the skipped middle (not just at one
    edge) is a known, accepted gap. "TAR" is captured by the 2-char head
    window's neighbour "R" being skipped, so "TARGET" never reconstructs."""
    page = "TA" + "R" + ("f" * 400) + "GET"  # "TARGET"'s middle "R" is skipped
    assert not title_present(page, "TARGET", window=2, tail_window=3)


class TestContentsHeaderRegexWidening:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "line",
        ["Contents", "CONTENTS", "Table of Contents", "Brief Contents", "Contents in Detail"],
    )
    def test_matches_every_publisher_variant(self, line: str) -> None:
        assert CONTENTS_HDR_RE.match(line)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "line",
        [
            "Contents of the Blood",  # real chapter title containing the word
            "See the Contents page for details",  # body prose, not a header
            "ELECTRIC CHARGES AND FIELDS",
        ],
    )
    def test_still_rejects_non_header_lines(self, line: str) -> None:
        assert not CONTENTS_HDR_RE.match(line)
