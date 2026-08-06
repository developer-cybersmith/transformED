"""The acceptance gate — one shared set of rules every rung must satisfy.

A rung whose candidate set fails falls through to the next. R5 cannot fail, so
the ladder is total.
"""

from __future__ import annotations

from collections.abc import Sequence

from .text import CONTENTS_HDR_RE, SECTION_ROW_RE, title_present
from .types import DetectedChapter

MIN_SPAN = 3
"""Minimum pages between consecutive chapter starts.

Load-bearing: contents-page false starts sit 1 page apart, so this is what
separates 'chapter 1 opens here' from 'this page lists chapter 1'.
"""

MAX_SHARE = 0.40
"""No single chapter may cover more than this share of a multi-chapter book.
A detection that collapses to one huge span is a failure wearing a result's
clothes."""

MIN_TITLE_HIT_RATE = 0.80
CONTENTS_SCAN_PAGES = 40
CONTENTS_MIN_SECTION_ROWS = 5


def contents_like_pages(page_texts: Sequence[str]) -> set[int]:
    """Pages that are a printed table of contents.

    Two signals, either sufficient: a bare `Contents` header in the first 8
    non-blank lines, or >=5 rows shaped `N.M  Title  <page>`. Only the front of
    the document is scanned — a body page can legitimately carry several section
    rows without being a contents page.
    """
    found: set[int] = set()
    for i, text in enumerate(page_texts[:CONTENTS_SCAN_PAGES]):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if any(CONTENTS_HDR_RE.match(ln) for ln in lines[:8]):
            found.add(i)
            continue
        if sum(1 for ln in lines if SECTION_ROW_RE.match(ln)) >= CONTENTS_MIN_SECTION_ROWS:
            found.add(i)
    return found


def passes_gate(
    chapters: Sequence[DetectedChapter],
    *,
    page_count: int,
    page_texts: Sequence[str],
    contents: set[int],
) -> bool:
    """The 7 rules. Returns False on the first violation.

    Rule 4 (no start on a contents page) is NOT implied by rule 6 (title on start
    page) — it is the rule rule 6 needs, because a contents page satisfies rule 6
    for every chapter in the book. Removing rule 4 regresses to the Phase 1 v1
    prototype, which accepted two contents pages as chapters.
    """
    # 1 — at least one chapter
    if not chapters:
        return False

    starts = [c.page_start for c in chapters]

    # 7 — inside the document, well-formed, non-overlapping
    for c in chapters:
        if not (0 <= c.page_start <= c.page_end < max(page_count, 1)):
            return False
    for prev, nxt in zip(chapters, chapters[1:], strict=False):
        if prev.page_end >= nxt.page_start:
            return False

    # 2 — strictly increasing starts
    if any(b <= a for a, b in zip(starts, starts[1:], strict=False)):
        return False

    # 3 — minimum span between starts (single-chapter documents are exempt)
    if len(chapters) > 1 and any(
        b - a < MIN_SPAN for a, b in zip(starts, starts[1:], strict=False)
    ):
        return False

    # 4 — no start on a contents page
    if any(c.page_start in contents for c in chapters):
        return False

    # 5 — no chapter swallowing the book (single-chapter documents are exempt)
    if len(chapters) > 1 and any(c.page_span > MAX_SHARE * page_count for c in chapters):
        return False

    # 6 — most starts carry their title
    hits = sum(
        1
        for c in chapters
        if c.page_start < len(page_texts) and title_present(page_texts[c.page_start], c.title)
    )
    return hits / len(chapters) >= MIN_TITLE_HIT_RATE
