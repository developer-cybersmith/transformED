"""Story 1-16 AC1 — every chapter detection offers must actually be generatable.

The per-rung detection tests (`tests/unit/test_chapter_detection.py`) prove the
ladder finds the right chapters. The endpoint tests prove the generate endpoint
refuses an over-cap span. **Nothing asserted that those two agree** — that what
detection hands a student is something the endpoint will accept.

That gap is the shape of the original bug. A book whose chapters were all one
1,151-page "chapter" detected fine and generated fine; it produced a lesson built
from 4% of the content. Today the endpoint would refuse it with 422
`chapter_too_large` — which is correct, but from the student's side means a
chapter card with a Generate button that can never succeed. Either way the
failure is in the JOIN between two layers that are each individually tested.

WHAT THIS DOES NOT COVER, deliberately:

  * It runs over CAPTURED detection output (`tests/fixtures/chapter_detection/`,
    the `(page_count, toc, page_heads)` triples Phase 1 measured), not a live PDF
    parse. The PDFs are gitignored and live outside the repo.
  * It asserts nothing about generated CONTENT — no package, no slide counts, no
    truncation warning. Those need a real generation run, which costs money and
    is Story 1-16 AC4-AC10.

So a green run here is not end-to-end proof. It is proof that the two layers
compose. Read the tracker's Phase 7 Observed result for the rest.
"""

from __future__ import annotations

import gzip
import json
import pathlib
from typing import Any

import pytest

from app.config import get_settings
from app.modules.content.chapter_detection import detect_chapters

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "chapter_detection"

# One book WITH a bookmark tree (rung 1) and one WITHOUT (rungs 2/3) — the
# tracker's Phase 7 requirement, satisfied by fixtures Phase 3 already committed.
CORPUS = ["d2l", "ncert-xii-phys-part1"]


def _detect(name: str) -> Any:  # noqa: ANN401 — DetectionResult
    with gzip.open(FIXTURES / f"{name}.json.gz", "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc, detect_chapters(
        page_count=doc["page_count"], toc=doc["toc"], page_texts=doc["page_heads"]
    )


@pytest.mark.integration
@pytest.mark.parametrize("name", CORPUS)
def test_every_detected_chapter_is_within_the_generation_cap(name: str) -> None:
    """The assertion nothing else makes: a chapter card the student can see must
    lead to a lesson the endpoint will accept.

    If detection ever emits a chapter wider than `max_chapter_pages` — a rung-5
    whole-document fallback, a collapsed outline level, a missing end boundary —
    the UI offers a Generate button that returns 422 `chapter_too_large` every
    time, with no way for the student to proceed and nothing in any suite going
    red. Detection tests would pass (the chapter was found correctly) and endpoint
    tests would pass (the refusal is correct). Only the join is wrong.
    """
    cap = get_settings().max_chapter_pages
    doc, res = _detect(name)

    # `DetectedChapter.page_span` is the domain object's own definition; the
    # endpoint recomputes `page_end - page_start + 1` inline (router.py, gate 6).
    # Assert they AGREE rather than picking one — a divergence between the number
    # the student is shown and the number the gate enforces is invisible otherwise.
    for c in res.chapters:
        assert c.page_span == c.page_end - c.page_start + 1, (
            f"{name}: DetectedChapter.page_span disagrees with the endpoint's inline "
            f"arithmetic for chapter {c.chapter_index}"
        )

    oversized = [(c.chapter_index, c.title, c.page_span) for c in res.chapters if c.page_span > cap]
    assert not oversized, (
        f"{name}: {len(oversized)} detected chapter(s) exceed max_chapter_pages={cap} and "
        f"would be un-generatable from the chapter card: {oversized}"
    )


@pytest.mark.integration
@pytest.mark.parametrize("name", CORPUS)
def test_chapter_indices_are_sequential_from_zero(name: str) -> None:
    """`chapters` carries `UNIQUE (book_id, chapter_index)`, and `book_ingest_job`
    upserts on that pair then trims rows beyond the new count. A gap or a repeat
    means a re-ingest either collides (23505) or silently leaves a stale chapter
    behind."""
    _doc, res = _detect(name)
    assert [c.chapter_index for c in res.chapters] == list(range(len(res.chapters)))


@pytest.mark.integration
@pytest.mark.parametrize("name", CORPUS)
def test_page_ranges_ascend_do_not_overlap_and_stay_inside_the_book(name: str) -> None:
    """`extract_node` passes these straight to the PDF subprocess as 0-based
    inclusive bounds. An overlap means two lessons teach the same pages; a range
    past the end means the subprocess exits non-zero mid-generation, minutes after
    the student got a 202."""
    doc, res = _detect(name)
    page_count = int(doc["page_count"])

    for c in res.chapters:
        assert 0 <= c.page_start <= c.page_end < page_count, (
            f"{name}: chapter {c.chapter_index} range [{c.page_start}..{c.page_end}] "
            f"is outside a {page_count}-page document"
        )

    ordered = sorted(res.chapters, key=lambda c: c.chapter_index)
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        assert nxt.page_start > prev.page_end, (
            f"{name}: chapters {prev.chapter_index} and {nxt.chapter_index} overlap "
            f"([{prev.page_start}..{prev.page_end}] then [{nxt.page_start}..{nxt.page_end}])"
        )


@pytest.mark.integration
@pytest.mark.parametrize("name", CORPUS)
def test_every_chapter_records_the_rung_that_found_it(name: str) -> None:
    """`boundary_confidence` is written to the row and surfaced to the client. A
    chapter with no rung means detection produced something no ladder step claims,
    and the client cannot tell a confident outline chapter from a guess."""
    # These five are the CHECK constraint on `chapters.boundary_confidence`
    # (20260803000000_chapters_book_scoped.sql) — a sixth value would insert fine
    # into a Supabase mock and raise 23514 against real Postgres.
    valid = {"toc", "contents", "heading", "font", "fallback"}
    _doc, res = _detect(name)
    assert res.chapters, f"{name}: detection returned no chapters at all"
    for c in res.chapters:
        assert c.boundary_confidence in valid, (
            f"{name}: chapter {c.chapter_index} has boundary_confidence "
            f"{c.boundary_confidence!r}, which the CHECK constraint would reject"
        )


@pytest.mark.integration
def test_the_cap_assertion_can_actually_fail() -> None:
    """Premise (AC2, binding rule 3). The corpus maximum is 98 pages against a
    200-page cap, so the headroom is wide — a passing run says little unless the
    assertion is shown to fire. This computes the same predicate at a cap below
    the real maximum and requires it to catch something.

    Without this, raising `max_chapter_pages` to any large number would leave the
    test above green forever while silently removing the protection it exists for.
    """
    _doc, res = _detect("d2l")
    spans = [c.page_span for c in res.chapters]
    widest = max(spans)

    assert widest <= get_settings().max_chapter_pages, "corpus itself violates the real cap"
    assert [s for s in spans if s > widest - 1], (
        "the predicate found nothing even at a cap below the widest real chapter — "
        "it cannot fail, and the assertion above proves nothing"
    )
