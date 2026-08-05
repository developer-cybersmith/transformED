"""Non-content filter.

Outlines list front and back matter as peers of real chapters: 6 of OpenStax
Biology's 53 entries, 8 of Math for Machine Learning's 20. Unfiltered, the
chapter picker offers "Index" as a lesson.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .text import norm
from .types import DetectedChapter

_BLOCKED_EXACT = frozenset(
    norm(t)
    for t in (
        "contents",
        "table of contents",
        "preface",
        "foreword",
        "acknowledgements",
        "acknowledgments",
        "index",
        "glossary",
        "bibliography",
        "references",
        "notation",
        "installation",
        "answer key",
        "answers",
        "exercises",
        "about the authors",
        "about the author",
        "colophon",
        "credits",
        "copyright",
        "dedication",
        "errata",
    )
)
_BLOCKED_PREFIX = ("appendix", "annexure")


def is_content(chapter: DetectedChapter) -> bool:
    """False for front/back matter that is not a teachable chapter."""
    n = norm(chapter.title)
    if not n:
        return False
    if n in _BLOCKED_EXACT:
        return False
    return not any(n.startswith(p) for p in _BLOCKED_PREFIX)


def drop_non_content(chapters: Sequence[DetectedChapter]) -> list[DetectedChapter]:
    """Drop front/back matter and RE-INDEX.

    `chapter_index` must stay sequential and gap-free over kept chapters, because
    Phase 2's UNIQUE (book_id, chapter_index) and the Phase 6 picker both key on
    it. Page ranges are deliberately NOT re-stitched: a gap where an appendix was
    dropped is honest, and silently widening a neighbour to cover it would make
    Phase 4 extract pages the chapter does not contain.
    """
    kept = [c for c in chapters if is_content(c)]
    return [
        DetectedChapter(
            title=re.sub(r"\s+", " ", c.title).strip(),
            page_start=c.page_start,
            page_end=c.page_end,
            chapter_index=i,
            boundary_confidence=c.boundary_confidence,
        )
        for i, c in enumerate(kept)
    ]
