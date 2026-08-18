"""Text helpers shared by the rungs. Pure, no I/O."""

from __future__ import annotations

import re

#: How much of a page counts as "the start of the page" for the title check.
#: Phase 1 measured start-page accuracy with this window; changing it invalidates
#: the 163/164 figure recorded in docs/reports/PHASE-1-TOC-SPIKE.md.
TITLE_WINDOW = 400

#: How much of the page's TAIL to also search, opt-in via `title_present`'s
#: `tail_window` kwarg (default 0 -- every existing caller is unaffected).
#: Not a Phase-1-measured constant like TITLE_WINDOW: some publishers (seen on
#: a No Starch Press title, session of 2026-08-15) typeset a chapter's opener
#: as a decorative "N / TITLE" block that pypdfium2 emits AFTER the body
#: paragraph, so it lands at the END of the page's extracted text, not the
#: start -- one measured case had it in the last 17 of 746 characters. Sized to
#: TITLE_WINDOW's own magnitude rather than an independently invented number.
#: See D115/D116 in docs/DEFECT-REGISTER.md for provenance and the accepted
#: residual gap (a title genuinely in the page's MIDDLE is still missed).
TITLE_TAIL_WINDOW = 400

WORD_NUM: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twentyone": 21,
    "twentytwo": 22,
    "twentythree": 23,
    "twentyfour": 24,
    "twentyfive": 25,
}
ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
}

_NUM_ALT = "|".join(WORD_NUM)
#: A chapter opener. NOTE the token list is English-only — Hindi editions use
#: अध्याय and are UNTESTED. Registered, not assumed (see the story's known gaps).
CHAPTER_RE = re.compile(
    rf"^\s*chapter\s*[\-–—:.]?\s*(\d{{1,2}}|{_NUM_ALT}|[ivx]{{1,5}})\b\s*(.*)$",
    re.IGNORECASE,
)
#: Whole-line anchored, deliberately: matching the bare word "contents" inside
#: a real sentence or chapter title would be a false positive. Widened
#: 2026-08-15 (D115) to also recognise "Brief Contents" / "Contents in Detail"
#: -- publisher house-style variants that the original bare "Contents" /
#: "Table of Contents" pair missed. Both original alternatives are unchanged
#: substrings of the new pattern, so no page that matched before can stop
#: matching now.
CONTENTS_HDR_RE = re.compile(
    r"^\s*(brief\s+contents|contents\s+in\s+detail|contents|table\s+of\s+contents)\s*$",
    re.IGNORECASE,
)
#: "1.1 Introduction 1" / "2.13 Electrostatics of Conductors 87"
SECTION_ROW_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s+(.*?)\s+(\d{1,4})\s*$")


def to_int(token: str) -> int | None:
    """'7' / 'seven' / 'vii' -> 7. None if it is not a chapter number."""
    t = token.strip().lower()
    if t.isdigit():
        return int(t)
    if t in WORD_NUM:
        return WORD_NUM[t]
    return ROMAN.get(t)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def strip_numbering(title: str) -> str:
    """'Chapter 3. Linear Algebra' -> 'Linear Algebra'; '3.1 Vectors' -> 'Vectors'."""
    t = re.sub(r"^(chapter|unit|part|section|appendix)\s+", "", title.strip(), flags=re.IGNORECASE)
    t = re.sub(r"^[0-9]+([.\-][0-9]+)*[.):\s]*\s*", "", t)
    return t.strip() or title.strip()


def title_present(
    page_text: str, title: str, *, window: int = TITLE_WINDOW, tail_window: int = 0
) -> bool:
    """Does `title` appear at the start of `page_text` (and, opt-in, its tail)?

    Normalised substring first, then a >=70% significant-word fallback for titles
    the PDF breaks across lines or hyphenates.

    `tail_window` defaults to 0, which reproduces the original head-only check
    byte-for-byte -- every pre-existing caller (rungs.py's `_snap()`, every
    direct test) is unaffected. When `tail_window > 0` and the page is longer
    than `window`, the search haystack becomes `page_text[:window] +
    page_text[-tail_window:]` -- a strict superset of the head-only haystack, so
    this can only turn a prior False into True, never the reverse (D115).
    Concatenation is safe because `norm()` strips whitespace/punctuation from
    the whole haystack before matching, the same way it already glues wrapped
    lines together within the head window.

    CAUTION: this is necessary but NOT sufficient evidence that a page opens a
    chapter — a contents page contains every title in the book and passes here.
    The gate's contents-page rule exists because this check was fooled in the
    Phase 1 v1 prototype. Never accept a start on this signal alone.
    """
    if not page_text or not title:
        return False
    head = page_text[:window]
    haystack = head + page_text[-tail_window:] if tail_window > 0 else head
    nh, nt = norm(haystack), norm(strip_numbering(title))
    if nt and nt in nh:
        return True
    words = [w for w in re.findall(r"[A-Za-z0-9]+", strip_numbering(title)) if len(w) > 2]
    if not words:
        return False
    return sum(1 for w in words if norm(w) in nh) / len(words) >= 0.7
