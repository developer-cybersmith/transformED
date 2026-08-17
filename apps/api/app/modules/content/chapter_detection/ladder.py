"""The detection ladder.

    R1 outline
      └─ reject → one shared text sweep →  R2 contents ⊕ R3 headings (MERGED)
                                             └─ reject → R4 font signals
                                                           └─ reject → R5 whole document

R2 and R3 are merged rather than tried in sequence. Phase 1 measured why: across
the three bookmark-less NCERT books an either/or ladder resolves 14 of 22
chapters, merged it resolves 22. Where the heading sweep fires, the contents page
is unparseable; where the contents page parses, the heading sweep finds nothing.

R5 always accepts, so the ladder is total — every book gets a chapter list, and
`boundary_confidence` records how much to trust it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .filter import drop_leading_unnumbered_front_matter, drop_non_content
from .gate import contents_like_pages, passes_gate
from .rungs import merge_r2_r3, r1_outline, r4_font_signals, r5_whole_document
from .types import DetectedChapter, DetectionResult, Rung

logger = logging.getLogger(__name__)


def detect_chapters(
    *,
    page_count: int,
    toc: Sequence[dict[str, Any]],
    page_texts: Sequence[str],
    fallback_title: str = "Full document",
) -> DetectionResult:
    """Detect chapter boundaries. Pure: no PDF, no DB, no network.

    Args:
        page_count: total pages in the document.
        toc: the PDF outline as ``{level, title, page_index}`` dicts (0-based
            `page_index`), exactly as `pypdfium2.PdfDocument.get_toc()` yields it.
            Empty when the document has no bookmark tree — 3 of Phase 1's 8 books.
        page_texts: per-page text. Only the head of each page is used, so callers
            may pass truncated pages; `gate.TITLE_WINDOW` is the minimum useful
            length.
        fallback_title: title for the R5 single chapter.

    Returns:
        DetectionResult with `chapters` (teachable, re-indexed from 0),
        `raw_chapters` (pre-filter, what the rung actually found) and `rung`.
    """
    if page_count <= 0:
        return DetectionResult(chapters=[], rung="fallback", raw_chapters=[])

    contents = contents_like_pages(page_texts)

    def accept(candidates: list[DetectedChapter], rung: Rung) -> DetectionResult | None:
        if not candidates:
            return None
        # FILTER BEFORE GATE, deliberately. A real outline legitimately lists
        # "Contents" as an entry, and its start page IS a contents page — gating
        # first would fail rule 4 on the honest entry and throw away a perfect
        # 53-chapter outline (OpenStax Biology does exactly this). The gate must
        # judge the teachable list.
        #
        # This does NOT weaken rule 4's real job: the false starts it exists to
        # catch are contents pages carrying a genuine chapter title
        # ("ELECTRIC CHARGES AND FIELDS"), which no blocklist removes.
        kept = drop_non_content(candidates)
        if not kept:
            return None
        # D117: a second, narrower filter pass — drop a LEADING run of
        # unnumbered entries (e.g. "Introduction") only when the rest of the
        # kept list is clearly numbered-chapter style ("1. X", "2. Y", ...).
        # Runs before the gate for the same reason drop_non_content does: the
        # gate judges the teachable list, not the raw candidates.
        kept = drop_leading_unnumbered_front_matter(kept)
        if not kept:
            return None
        if not passes_gate(kept, page_count=page_count, page_texts=page_texts, contents=contents):
            logger.info("chapter_detection: rung %s rejected by the gate", rung)
            return None
        logger.info(
            "chapter_detection: rung %s accepted — %d chapters (%d before filtering)",
            rung,
            len(kept),
            len(candidates),
        )
        return DetectionResult(chapters=kept, rung=rung, raw_chapters=candidates)

    # R1 — cheapest by far: no text needed at all. 0.03-1.76 s on Phase 1's books.
    result = accept(r1_outline(page_count, toc), "toc")
    if result is not None:
        return result

    # R2 + R3 — merged, over the one shared text sweep.
    merged, merged_rung = merge_r2_r3(page_count, page_texts, contents)
    result = accept(merged, merged_rung)
    if result is not None:
        return result

    # R4 — existing font-signal detector. Wired, not tuned (D28 pinned).
    result = accept(r4_font_signals(page_count, page_texts, contents), "font")
    if result is not None:
        return result

    # R5 — terminal. Labelled so a consumer knows detection found nothing.
    logger.warning(
        "chapter_detection: no rung produced a usable chapter list for a %d-page "
        "document — falling back to one whole-document chapter",
        page_count,
    )
    fallback = r5_whole_document(page_count, fallback_title)
    return DetectionResult(chapters=fallback, rung="fallback", raw_chapters=fallback)
