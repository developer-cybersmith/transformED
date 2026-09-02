"""Guards the "long" eval fixtures actually exercise chapter detection.

Story context: the eval harness's `_build_long` builder (generate_eval_pdfs.py)
used to give every page in a 100-400 page fixture the identical bold-14pt
"Section X.Y" style, with no real PDF outline at all. Real chapter detection
(app/modules/content/chapter_detection/) can never find a boundary in that
shape, so it fell through its whole ladder to R5 and treated the ENTIRE
100-400 page document as one single chapter -- which is what made a
`--run-live-eval` attempt run for 6+ hours without finishing: the pipeline
built a lesson from a 100-400 page "chapter" instead of the ~40-page chapter
the system's timing/cost assumptions (CLAUDE.md §9) are built around.

These tests run the REAL detection path (`_extract_text_only` ->
`detect_chapters`, no mocking, no network, no DB, no LLM) against each long
fixture's actual bytes and assert it produces real, page-bounded chapters
rather than the fallback. Binding rule 2 (CLAUDE.md): assert an observable
outcome, not a mock's belief.
"""

from __future__ import annotations

import pytest

from app.modules.content.chapter_detection import detect_chapters
from app.workers.jobs.book_ingest import _extract_text_only
from tests.fixtures.generate_eval_pdfs import _GENERATORS

#: A little slack over the 40-page target interval (`_CHAPTER_INTERVAL` in
#: generate_eval_pdfs.py) -- catches a regression if someone widens the
#: interval without updating this bound, without being so tight that normal
#: chapter-boundary rounding (a book's real chapters are never exactly N
#: pages) trips it.
_MAX_CHAPTER_SPAN = 45

_LONG_FIXTURES: dict[str, int] = {
    "long_100page": 100,
    "long_150page": 150,
    "long_250page": 250,
    "long_400page": 400,
}


@pytest.mark.unit
@pytest.mark.parametrize("key,expected_page_count", sorted(_LONG_FIXTURES.items()))
async def test_long_fixture_produces_real_page_bounded_chapters(
    key: str, expected_page_count: int
) -> None:
    pdf_bytes = _GENERATORS[key]()

    extracted = await _extract_text_only(pdf_bytes)

    # Belt-and-suspenders: protects this test's own premise, and
    # test_generated_pdfs_satisfy_their_category_page_count_boundary's, from
    # each other silently drifting.
    assert extracted["page_count"] == expected_page_count, (
        f"{key}: expected exactly {expected_page_count} pages, got {extracted['page_count']}"
    )

    result = detect_chapters(
        page_count=extracted["page_count"],
        toc=extracted["toc"],
        page_texts=extracted["page_texts"],
        fallback_title=key,
    )

    assert result.rung != "fallback", (
        f"{key}: detection fell all the way through to the whole-document "
        f"fallback (rung={result.rung!r}) -- the fixture still gives real "
        f"chapter detection nothing to split on."
    )
    assert len(result.chapters) > 1, (
        f"{key}: detection found only {len(result.chapters)} chapter(s); "
        f"expected multiple ~40-page chapters."
    )

    for chapter in result.chapters:
        assert chapter.page_span <= _MAX_CHAPTER_SPAN, (
            f"{key}: chapter {chapter.chapter_index} ({chapter.title!r}) spans "
            f"{chapter.page_span} pages ({chapter.page_start}-{chapter.page_end}), "
            f"over the {_MAX_CHAPTER_SPAN}-page bound."
        )

    # No gaps or overlaps: the chapters, in order, cover every page of the
    # document exactly once. Chapters are sorted by page_start (the ladder's
    # own `_close` builds them that way) and the fixture has no front/back
    # matter for `drop_non_content` to drop, so span coverage should sum to
    # exactly the page count with the first chapter starting at page 0 and
    # the last ending at the final page.
    assert result.chapters[0].page_start == 0, (
        f"{key}: first chapter does not start at page 0 (starts at {result.chapters[0].page_start})"
    )
    assert result.chapters[-1].page_end == expected_page_count - 1, (
        f"{key}: last chapter does not end at the final page "
        f"(ends at {result.chapters[-1].page_end}, expected {expected_page_count - 1})"
    )
    total_span = sum(c.page_span for c in result.chapters)
    assert total_span == expected_page_count, (
        f"{key}: chapter spans sum to {total_span}, expected exactly "
        f"{expected_page_count} (a gap or overlap somewhere)."
    )
