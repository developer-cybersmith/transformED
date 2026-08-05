"""The five rungs. Each takes the same inputs and returns candidates; the ladder
applies the gate. All pure — no PDF, no DB, no I/O.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from .gate import MIN_SPAN
from .text import CHAPTER_RE, SECTION_ROW_RE, title_present, to_int
from .types import DetectedChapter, Rung

# ── R1 level heuristic (Phase 1: correct on 5 of 5 books, no manual override) ──
MIN_ENTRIES, MAX_ENTRIES = 4, 80
MIN_MEDIAN_SPAN = 3
HEAD_LINES = 4
SNAP_WINDOW = 8


def _close(starts: list[tuple[str, int]], page_count: int, rung: Rung) -> list[DetectedChapter]:
    """Turn (title, start) pairs into chapters, each ending where the next begins."""
    out: list[DetectedChapter] = []
    for i, (title, start) in enumerate(starts):
        end = starts[i + 1][1] - 1 if i + 1 < len(starts) else page_count - 1
        out.append(DetectedChapter(title or "Chapter", start, max(end, start), i, rung))
    return out


def r1_outline(page_count: int, toc: Sequence[dict[str, Any]]) -> list[DetectedChapter]:
    """The PDF's own outline, at the coarsest level that looks like chapters.

    Heuristic: lowest level with 4-80 entries and a median span >= 3 pages. On
    Phase 1's books this chose level 0 four times and level 1 once (Math for
    Machine Learning, whose level 0 is 3 'Part' entries spanning 163 pages each).
    """
    entries = [e for e in toc if e.get("page_index") is not None]
    if not entries:
        return []
    for level in sorted({int(e["level"]) for e in entries}):
        at = [e for e in entries if int(e["level"]) == level]
        if not (MIN_ENTRIES <= len(at) <= MAX_ENTRIES):
            continue
        starts = [int(e["page_index"]) for e in at]
        spans = [
            (starts[i + 1] if i + 1 < len(starts) else page_count) - s for i, s in enumerate(starts)
        ]
        if statistics.median(spans) < MIN_MEDIAN_SPAN:
            continue
        pairs = [(str(e["title"]).strip(), int(e["page_index"])) for e in at]
        return _close(pairs, page_count, "toc")
    return []


def _openers(page_texts: Sequence[str], skip: set[int]) -> list[tuple[int, int, str]]:
    """(chapter_number, page_index, title) for pages that OPEN a chapter."""
    found: list[tuple[int, int, str]] = []
    for i, text in enumerate(page_texts):
        if i in skip:
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:8]
        for j, line in enumerate(lines[:HEAD_LINES]):
            m = CHAPTER_RE.match(line)
            if not m:
                continue
            num = to_int(m.group(1))
            if num is None:
                continue
            tail = (m.group(2) or "").strip()
            title = tail or (lines[j + 1] if j + 1 < len(lines) else "")
            found.append((num, i, title.strip()))
            break
    return found


def _dedupe_monotonic(by_num: dict[int, tuple[int, str]]) -> list[tuple[str, int]]:
    """Keep chapters in number order, enforcing the minimum-span floor."""
    starts: list[tuple[str, int]] = []
    for num in sorted(by_num):
        page, title = by_num[num]
        if starts and page - starts[-1][1] < MIN_SPAN:
            continue
        starts.append((title or f"Chapter {num}", page))
    return starts


def r3_heading_sweep(
    page_count: int, page_texts: Sequence[str], contents: set[int]
) -> list[DetectedChapter]:
    """In-body `CHAPTER n` openers.

    Two filters do the real work. Keeping only the FIRST page per chapter number
    drops back-matter references (`p 175 Chapter 1`, `p 186 CHAPTER 9` — pages
    that mention a chapter rather than open it). The MIN_SPAN floor drops
    contents-page runs, whose "chapters" sit one page apart.
    """
    first: dict[int, tuple[int, str]] = {}
    for num, page, title in _openers(page_texts, contents):
        first.setdefault(num, (page, title))
    return _close(_dedupe_monotonic(first), page_count, "heading")


def r2_contents_page(page_texts: Sequence[str], contents: set[int]) -> list[tuple[int, str, int]]:
    """Parse the printed contents block -> (chapter_number, title, printed_page).

    The first section row beneath each `CHAPTER n` header carries that chapter's
    printed start page. Returns PRINTED pages, not PDF indices — resolving them is
    the merge's job, by title-anchored search rather than offset arithmetic.
    """
    if not contents:
        return []
    lines: list[str] = []
    for p in sorted(contents):
        lines += [ln.strip() for ln in page_texts[p].splitlines() if ln.strip()]

    entries: list[tuple[int, str, int]] = []
    cur: int | None = None
    cur_title = ""
    for k, line in enumerate(lines):
        m = CHAPTER_RE.match(line)
        if m and to_int(m.group(1)) is not None:
            cur = to_int(m.group(1))
            tail = (m.group(2) or "").strip()
            cur_title = tail or (lines[k + 1] if k + 1 < len(lines) else "")
            continue
        row = SECTION_ROW_RE.match(line)
        if row and cur is not None and int(row.group(1)) == cur:
            entries.append((cur, cur_title, int(row.group(4))))
            cur = None  # the first section under a chapter defines its start
    return entries


def _snap(
    page_texts: Sequence[str], predicted: int, title: str, skip: set[int], after: int
) -> int | None:
    """Nearest non-contents page to `predicted` whose head carries `title`.

    Title-anchored, deliberately NOT offset arithmetic: Phase 1 measured a
    folio-mode offset estimator at 28% consensus and 2 pages wrong, while this
    resolved 8 of 8 chapters in the same book with no offset at all.
    """
    n = len(page_texts)
    for d in sorted(range(-SNAP_WINDOW, SNAP_WINDOW + 1), key=abs):
        p = predicted + d
        if after < p < n and p not in skip and title_present(page_texts[p], title):
            return p
    for p in range(max(after + 1, 0), n):  # last resort: forward scan
        if p not in skip and title_present(page_texts[p], title):
            return p
    return None


def merge_r2_r3(
    page_count: int, page_texts: Sequence[str], contents: set[int]
) -> tuple[list[DetectedChapter], Rung]:
    """R3 authoritative, R2 fills the gaps.

    Phase 1's headline result: run as either/or these rungs resolve 14 of 22
    chapters across the three NCERT books; merged they resolve 22. The books are
    complementary — where the heading sweep fires the contents page is
    unparseable, and vice versa.
    """
    by_num: dict[int, tuple[int, str]] = {}
    for num, page, title in _openers(page_texts, contents):
        by_num.setdefault(num, (page, title))
    from_headings = bool(by_num)

    for num, title, printed in r2_contents_page(page_texts, contents):
        if num in by_num or not title:
            continue
        anchor = max((p for p, _ in by_num.values()), default=-1)
        placed = _snap(page_texts, printed, title, contents, after=anchor)
        if placed is not None:
            by_num[num] = (placed, title)

    rung: Rung = "heading" if from_headings else "contents"
    return _close(_dedupe_monotonic(by_num), page_count, rung), rung


def r4_font_signals(
    page_count: int, page_texts: Sequence[str], contents: set[int]
) -> list[DetectedChapter]:
    """Existing `detect_headings()` over the page texts.

    Wired as a rung but NOT tuned here — D28 is pinned: the font strategy
    outranks the explicit `Chapter N:` regex, so a chapter can rank below its own
    subsections. Tolerated, not fixed (fixing it is a detection behaviour change
    and belongs with the Sprint 3 docling migration).
    """
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    offsets: list[int] = []
    running = 0
    for text in page_texts:
        offsets.append(running)
        running += len(text) + 1

    def page_of(char_offset: int) -> int:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= char_offset:
                lo = mid
            else:
                hi = mid - 1
        return max(lo, 0)

    raw_text = "\n".join(page_texts)
    heads = [h for h in detect_headings(raw_text, []) if h.get("level") == "chapter"]

    starts: list[tuple[str, int]] = []
    for h in heads:
        page = page_of(int(h["char_offset"]))
        if page in contents:
            continue
        if starts and page - starts[-1][1] < MIN_SPAN:
            continue
        starts.append((str(h["text"]).strip(), page))
    return _close(starts, page_count, "font")


def r5_whole_document(page_count: int, title: str = "Full document") -> list[DetectedChapter]:
    """Terminal rung: the whole PDF as one chapter.

    This is what the pipeline does implicitly today. Making it explicit AND
    labelled `fallback` is the point — a consumer can then tell a real chapter
    list from a degenerate one, which `graph.py`'s hardcoded row never allowed.
    """
    if page_count <= 0:
        return []
    return [DetectedChapter(title, 0, page_count - 1, 0, "fallback")]
