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
        "about the technical reviewer",
        "about the reviewers",
        "colophon",
        "credits",
        "copyright",
        "dedication",
        "errata",
        # Added 2026-08-15 (D116) — a 6th real book (No Starch Press) whose
        # front/back matter the original 5-book Phase-1 blocklist never saw.
        # NOTE: "introduction" is deliberately NOT here. It would strip this
        # exact book's front-matter Introduction, but D2L's real, pinned
        # Chapter 1 (tests/fixtures/chapter_detection/d2l.json.gz, toc
        # page_index 40) is ALSO titled bare "Introduction" -- confirmed by
        # direct check against the fixture before adding this entry. A book
        # whose chapters are unnumbered (D2L) can have "Introduction" as a
        # real, teachable chapter 1; a book whose chapters are numbered
        # ("1. EDR-Chitecture" ...) can have it as front matter preceding the
        # numbered sequence. Exact-title blocking can't tell these apart
        # safely -- see D116's residual-gap note in DEFECT-REGISTER.md.
        "cover",
        "back cover",
        "title page",
        "brief contents",
        "contents in detail",
    )
)
_BLOCKED_PREFIX = (
    "appendix",
    "annexure",
    # norm() strips whitespace before comparison, so this must be spaceless —
    # a literal "praise for" here would silently never match (D116).
    "praisefor",
)


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


#: A title carrying the publisher's own leading chapter number, e.g.
#: "1. EDR-Chitecture" or "12. Microsoft-Windows-Threat-Intelligence".
#: Deliberately requires punctuation right after the digit(s) -- "Chapter 1
#: The Study of Life" (OpenStax) does NOT start with a digit at all, and a
#: bare "1 Introduction" (no punctuation) is excluded on purpose: it is
#: indistinguishable from an ordinary sentence starting with a number, so
#: matching it would widen this rung's blast radius past what D117 measured.
_NUMBERED_TITLE_RE = re.compile(r"^\d{1,3}[.:)]\s+\S")

#: D117 (2026-08-17). If at least this fraction of a rung's kept candidates
#: carry an explicit leading chapter number in their own title text, the book
#: is treated as numbered-chapter style. Chosen as a clear margin above the
#: one measured real case (Evading EDR: 13 of 14 kept titles, 92.9%) and a
#: clear margin below "some but not most" -- not fit to n=1, but not
#: unexamined either. Checked against all 5 Phase-1 pinned books before
#: shipping: every one is 0/N numbered by this exact regex, so the rung never
#: even reaches the threshold check for any of them.
_MIN_NUMBERED_FRACTION = 0.7


def drop_leading_unnumbered_front_matter(
    chapters: Sequence[DetectedChapter],
) -> list[DetectedChapter]:
    """Drop a leading run of unnumbered entries when the book is otherwise
    numbered-chapter style, and RE-INDEX. Call AFTER `drop_non_content`.

    D117: exact-title blocking (`drop_non_content`'s blocklist) cannot tell
    "front matter preceding a numbered chapter sequence" (Evading EDR's bare
    "Introduction" before "1. EDR-Chitecture") from "a real, unnumbered
    chapter 1" (Dive into Deep Learning's real Chapter 1 is ALSO bare
    "Introduction", and every other D2L chapter is unnumbered too) -- adding
    "introduction" to that blocklist would have silently deleted a real,
    already-pinned chapter (D116's residual gap).

    This looks at title SHAPE across the whole kept list instead of any one
    title's text, so it naturally does nothing on D2L (0 numbered titles) and
    fires on Evading EDR (13 of 14 numbered) -- verified directly against all
    6 fixtures in `tests/fixtures/chapter_detection/`, not assumed.

    Scoped to the LEADING run only: an unnumbered entry appearing AFTER the
    first numbered one is left alone. No pinned or captured book has ever
    shown that shape, and dropping mid-sequence entries risks hiding a real
    chapter with a deliberately unnumbered editorial title.
    """
    if not chapters:
        return list(chapters)
    numbered = [bool(_NUMBERED_TITLE_RE.match(c.title.strip())) for c in chapters]
    if not any(numbered) or sum(numbered) / len(chapters) < _MIN_NUMBERED_FRACTION:
        return list(chapters)
    first_numbered = numbered.index(True)
    kept = list(chapters[first_numbered:])
    return [
        DetectedChapter(
            title=c.title,
            page_start=c.page_start,
            page_end=c.page_end,
            chapter_index=i,
            boundary_confidence=c.boundary_confidence,
        )
        for i, c in enumerate(kept)
    ]
