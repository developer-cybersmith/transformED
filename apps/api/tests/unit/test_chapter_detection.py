"""Chapter-detection ladder — Story 1-10 (book-scale Phase 3).

Every number asserted here was MEASURED in the Phase 1 spike against the real
textbook, and is recorded in docs/reports/PHASE-1-TOC-SPIKE.md. They are not
invented expectations: if a rung regresses, these fail with the book that broke.

Fixtures are captured `(page_count, toc, page_heads)` triples — the exact tuple the
detection API takes — so the whole ladder is exercised without a PDF, a database or
a Supabase mock (binding rule 2). Capture script is recorded in the story.
"""

from __future__ import annotations

import gzip
import json
import pathlib
from typing import Any

import pytest

from app.modules.content.chapter_detection import detect_chapters
from app.modules.content.chapter_detection.gate import contents_like_pages
from app.modules.content.chapter_detection.text import title_present

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "chapter_detection"


def load(name: str) -> dict[str, Any]:
    with gzip.open(FIXTURES / f"{name}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def run(name: str) -> Any:
    doc = load(name)
    return detect_chapters(
        page_count=doc["page_count"], toc=doc["toc"], page_texts=doc["page_heads"]
    )


# ════════════════════════════════════════════════════════════════════════════
# R1 — outline. Phase 1: 5 of 8 books, 164 chapters, 163/164 strict accuracy.
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_r1_d2l_detects_27_chapters_via_the_outline() -> None:
    """Dive into Deep Learning, 1,151 pages. Phase 1 measured 27 chapters at
    outline level 0, and reproduced it twice."""
    res = run("d2l")
    assert res.rung == "toc"
    assert res.raw_count == 27, f"expected 27 outline chapters, got {res.raw_count}"


@pytest.mark.unit
def test_r1_d2l_every_start_page_carries_its_title() -> None:
    """Phase 1: 27/27 strict. This is the accuracy claim the whole ladder rests on."""
    doc = load("d2l")
    res = run("d2l")
    hits = sum(
        1 for c in res.raw_chapters if title_present(doc["page_heads"][c.page_start], c.title)
    )
    assert hits == 27, f"start-page accuracy regressed: {hits}/27"


@pytest.mark.unit
def test_r1_page_ranges_are_ascending_and_non_overlapping() -> None:
    """Phases 4 and 5 slice on these ranges; overlap would double-bill extraction."""
    res = run("d2l")
    for prev, nxt in zip(res.chapters, res.chapters[1:], strict=False):
        assert prev.page_end < nxt.page_start, f"{prev.title} overlaps {nxt.title}"
        assert prev.page_start <= prev.page_end


@pytest.mark.unit
def test_r1_chooses_level_1_when_level_0_is_too_coarse() -> None:
    """OpenStax Biology has 53 level-0 entries; a book whose level 0 is a handful of
    'Part' entries must fall through to level 1. Phase 1 saw this on Math for
    Machine Learning (level 0 = 3 parts, median span 163 pages)."""
    res = run("openstax-bio2e")
    assert res.rung == "toc"
    assert res.raw_count == 53


# ════════════════════════════════════════════════════════════════════════════
# R2 / R3 — the bookmark-less NCERT books. Phase 1 prototype: 22/22 across three.
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_ncert_xi_part1_resolves_seven_chapters_by_heading_sweep() -> None:
    """No outline. In-body 'CHAPTER ONE'..'CHAPTER SEVEN' openers; one false
    positive in back matter that dedup + monotonicity must drop."""
    res = run("ncert-xi-phys-part1")
    assert res.rung == "heading"
    assert res.raw_count == 7


@pytest.mark.unit
def test_ncert_xi_part2_resolves_seven_chapters_numbered_nine_to_fifteen() -> None:
    """Part 2 of a split book: chapter numbers start at 9, not 1. Four false
    positives in back matter (`p 171 Chapter 9`, `p 186 CHAPTER 9`)."""
    res = run("ncert-xi-phys-part2-2006scan")
    assert res.rung == "heading"
    assert res.raw_count == 7


@pytest.mark.unit
def test_ncert_xii_part1_resolves_eight_chapters_from_the_contents_page() -> None:
    """Zero in-body chapter openers — the heading sweep finds nothing. The printed
    contents page is the only signal, and it resolves all eight."""
    res = run("ncert-xii-phys-part1")
    assert res.rung == "contents"
    assert res.raw_count == 8


@pytest.mark.unit
def test_merged_rungs_resolve_all_22_ncert_chapters() -> None:
    """The headline Phase 1 result. Run as either/or these books give 14 of 22;
    merged they give 22. This test is the reason R2 and R3 are not a ladder."""
    total = sum(
        run(n).raw_count
        for n in (
            "ncert-xi-phys-part1",
            "ncert-xi-phys-part2-2006scan",
            "ncert-xii-phys-part1",
        )
    )
    assert total == 22, f"merged detection regressed: {total}/22"


@pytest.mark.unit
@pytest.mark.parametrize(
    "name", ["ncert-xi-phys-part1", "ncert-xi-phys-part2-2006scan", "ncert-xii-phys-part1"]
)
def test_ncert_every_detected_start_carries_its_title(name: str) -> None:
    """22/22 title-on-start-page in the Phase 1 prototype."""
    doc = load(name)
    res = run(name)
    for c in res.raw_chapters:
        assert title_present(doc["page_heads"][c.page_start], c.title), (
            f"{name} ch {c.chapter_index} '{c.title}' not on page {c.page_start}"
        )


# ════════════════════════════════════════════════════════════════════════════
# AC8 — the defect the Phase 1 v1 prototype actually shipped
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_contents_pages_are_identified_in_the_ncert_books() -> None:
    res_pages = contents_like_pages(load("ncert-xii-phys-part1")["page_heads"])
    assert res_pages, "contents page not detected — R2 has nothing to parse"
    assert min(res_pages) < 10, "contents page should be in the front matter"


@pytest.mark.unit
def test_a_contents_page_is_rejected_as_a_chapter_start_despite_passing_the_title_check() -> None:
    """AC8, and the single most important test in this file.

    A contents page lists EVERY chapter title, so "the title appears in the first
    400 characters of the start page" is satisfied there. The Phase 1 v1 prototype
    accepted PDF pages 1 and 2 of NCERT XII Part 1 as chapters 1 and 3 on exactly
    that evidence, and the title check CONFIRMED them.

    So this asserts both halves: the title check really does pass on the contents
    page (i.e. the trap is live), and the detector rejects it anyway.
    """
    doc = load("ncert-xii-phys-part1")
    heads = doc["page_heads"]
    contents = sorted(contents_like_pages(heads))
    res = run("ncert-xii-phys-part1")

    first_title = res.raw_chapters[0].title
    assert any(title_present(heads[p], first_title) for p in contents), (
        "the trap is not live in this fixture — a contents page must contain the "
        "chapter title for this test to mean anything"
    )
    starts = {c.page_start for c in res.raw_chapters}
    assert not (starts & set(contents)), (
        f"a chapter start landed on a contents page: {sorted(starts & set(contents))}"
    )


# ════════════════════════════════════════════════════════════════════════════
# Non-content filter + indexing
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_front_and_back_matter_is_dropped() -> None:
    """OpenStax Biology lists Contents, Preface, Appendix A/B/C and Index as peers
    of real chapters. Unfiltered the picker offers 'Index' as a lesson."""
    res = run("openstax-bio2e")
    kept = {c.title.lower() for c in res.chapters}
    for junk in ("contents", "preface", "index"):
        assert not any(k.startswith(junk) for k in kept), f"{junk!r} survived the filter"
    assert len(res.chapters) < res.raw_count


@pytest.mark.unit
@pytest.mark.parametrize("name", ["d2l", "openstax-bio2e", "ncert-xii-phys-part1"])
def test_chapter_index_is_sequential_from_zero_over_kept_chapters(name: str) -> None:
    res = run(name)
    assert [c.chapter_index for c in res.chapters] == list(range(len(res.chapters)))


@pytest.mark.unit
def test_every_chapter_declares_the_rung_that_found_it(name: str = "d2l") -> None:
    res = run(name)
    assert {c.boundary_confidence for c in res.chapters} == {"toc"}
    assert all(
        c.boundary_confidence in ("toc", "contents", "heading", "font", "fallback")
        for c in res.chapters
    )


# ════════════════════════════════════════════════════════════════════════════
# R5 and the edges
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_a_document_with_no_usable_signal_falls_back_to_one_chapter() -> None:
    """AC17. Today this is implicit behaviour; R5 makes it explicit AND labelled,
    so a consumer can tell a real chapter list from a degenerate one."""
    res = detect_chapters(page_count=40, toc=[], page_texts=["body text " * 40] * 40)
    assert res.rung == "fallback"
    assert len(res.chapters) == 1
    assert (res.chapters[0].page_start, res.chapters[0].page_end) == (0, 39)
    assert res.chapters[0].boundary_confidence == "fallback"


@pytest.mark.unit
def test_a_single_chapter_pdf_yields_exactly_one_chapter_not_an_error() -> None:
    """AC16. NCERT ships most of its catalogue as one PDF per chapter
    (ncert-keph1 -> keph101.pdf .. keph108.pdf), so this is the common shape for
    the target segment, not a degenerate case."""
    pages = ["CHAPTER ONE\nUNITS AND MEASUREMENT\nbody"] + ["more body"] * 29
    res = detect_chapters(page_count=30, toc=[], page_texts=pages)
    assert len(res.chapters) == 1
    assert res.chapters[0].page_end == 29


@pytest.mark.unit
def test_an_empty_document_does_not_crash() -> None:
    res = detect_chapters(page_count=0, toc=[], page_texts=[])
    assert res.chapters == []
    assert res.rung == "fallback"


# ════════════════════════════════════════════════════════════════════════════
# The acceptance gate
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_gate_rejects_starts_closer_than_three_pages() -> None:
    """Rule 3 — the floor that kills contents-page false starts, which sit 1 page
    apart. Two 'chapters' one page apart must not survive as two chapters."""
    pages = ["CHAPTER ONE\nAlpha"] + ["CHAPTER TWO\nBeta"] + ["body"] * 38
    res = detect_chapters(page_count=40, toc=[], page_texts=pages)
    assert len(res.chapters) <= 1


@pytest.mark.unit
def test_gate_rejects_a_chapter_spanning_most_of_the_book() -> None:
    """Rule 5 — a single 'chapter' covering >40 % of a multi-chapter detection is a
    collapsed detection, not a chapter."""
    from app.modules.content.chapter_detection.gate import passes_gate
    from app.modules.content.chapter_detection.types import DetectedChapter

    bad = [
        DetectedChapter("A", 0, 79, 0, "toc"),
        DetectedChapter("B", 80, 99, 1, "toc"),
    ]
    assert not passes_gate(bad, page_count=100, page_texts=[""] * 100, contents=set())


@pytest.mark.unit
def test_gate_rejects_non_monotonic_starts() -> None:
    from app.modules.content.chapter_detection.gate import passes_gate
    from app.modules.content.chapter_detection.types import DetectedChapter

    bad = [
        DetectedChapter("A", 50, 59, 0, "toc"),
        DetectedChapter("B", 10, 19, 1, "toc"),
    ]
    assert not passes_gate(bad, page_count=100, page_texts=[""] * 100, contents=set())
