# Story: Chapter titles silently truncated when they wrap onto the PDF's next line

**Discovered:** 2026-09-24, live production smoke-test of chapter generation, inspecting
the actually-stored chapter titles for a real successfully-ingested book
(`_OceanofPDF.com_The_Hitchhikers_Guide_to_Python_-_Kenneth_Reitz.pdf`, book_id
`9d3345ef-c196-4fc1-b618-35a62896af76`, 11 chapters, `boundary_confidence='heading'` on
every one). Registered as **D182** in `docs/DEFECT-REGISTER.md`.

## Problem

`SELECT title FROM chapters WHERE book_id = '9d3345ef-...'` returned, verbatim:

```
". Picking an", ". Properly", ". Your", ". Writing Great", ". Reading Great",
". Shipping Great", ". User", ". Code Management", ". Software", ". Data", ". Data"
```

Every title is truncated to 1-3 words and carries a stray leading `". "`. Confirmed against
the real extracted page text (page 11, 0-based, the chapter 1 opener):

```
'Chapter 1. Picking an\r\nInterpreter\r\nThe State of Python 2 Versus Python\r\n3\r\n...'
```

The real title is **"Picking an Interpreter"**, but the PDF's typography wraps it across two
physical lines ("Chapter 1. Picking an" / "Interpreter") — extremely common chapter-opener
styling, not specific to this book.

Two independent bugs compound in `apps/api/app/modules/content/chapter_detection/rungs.py`'s
`_openers()` (used by both the `heading` rung, `r3_heading_sweep`, and `r2_contents_page`'s
contents-page parsing — both consume `CHAPTER_RE`'s `group(2)` as the title "tail"):

1. **`CHAPTER_RE`** (`chapter_detection/text.py`) has an optional separator
   (`[\-–—:.]?`) **before** the chapter number (for `"Chapter: 1"` / `"Chapter - 1"`) but
   nothing symmetric **after** it. A line like `"Chapter 1. Picking an"` — number
   immediately followed by a period with no space — leaves the period as part of
   `group(2)`, the captured "tail". `.strip()` only removes whitespace, not the leading
   `.`, so every title on this rung that uses a period/colon/dash separator after the
   number ships with a stray leading punctuation character.
2. **`_openers()`** takes `group(2)` (or, if empty, exactly the *single* next line) as
   the whole title and never looks further. When the title's remainder is typeset on its
   own separate visual line — as it is here — that remainder is silently dropped. No
   error, no degradation flag: a garbage 1-3-word fragment ships to `books`/`chapters` and
   from there into every lesson generated from that chapter, with `boundary_confidence`
   still reported as the normal `'heading'` rung (nothing signals degraded confidence).

This is exactly the class of defect CLAUDE.md's Silent Truncation rule and Scale Contract
Q2 exist to catch: a fixed assumption (title fits on the chapter-number's own line) meeting
a variable input (real publisher typography) that fails *silently and cheaply* rather than
loudly.

**Confirmed no existing regression risk**: neither `tests/unit/test_chapter_detection.py`
nor `test_chapter_detection_text.py` exercises `_openers()`'s title-continuation behavior —
the D2L/NCERT/`evading-edr` fixtures resolve via the `toc`/`contents` rungs, whose titles
come from a different source (the PDF outline or printed contents-page rows), not
`_openers()`'s line-wrap handling. The "Phase 1: correct on 5 of 5 books" claim in
`rungs.py`'s module docstring is about `r1_outline`, which this story does not touch.

## Fix

1. **`CHAPTER_RE`**: add the same optional separator group after the number
   (`\b\s*[\-–—:.]?\s*(.*)$`), symmetric with the existing before-number handling. Strictly
   cleans up `group(2)` for lines shaped like `"Chapter 1. Title"` / `"Chapter 1: Title"` —
   never changes behavior for lines with no separator character present.
2. **`_openers()`**: when the captured/fallback title is short (fewer than
   `_TITLE_WORD_TARGET` words), stitch in up to `_MAX_TITLE_CONTINUATION_LINES` more
   physical lines — but only lines that themselves look like a title continuation, not a
   new chapter opener (`CHAPTER_RE`), not a TOC section row (`SECTION_ROW_RE`), and short
   enough (`<= 6` words) to be implausible as ordinary body prose. Both the word-count
   target and the line-count bound are explicit, fixed budgets — matching CLAUDE.md's
   "every fixed budget must be bounded and stated" rule, not an unbounded absorb-until-you-
   find-something loop.

This is a heuristic, not a structural fix (real structural fix = font-size-aware extraction,
already deferred to the Sprint 3 docling migration per `r4_font_signals`'s own comment on
D28). It is explicitly bounded and tested against both the failure it fixes and the
over-absorption failure mode it must not introduce.

## Acceptance Criteria

1. **AC1**: `CHAPTER_RE.match("Chapter 1. Picking an").group(2) == "Picking an"` (no
   leading period) — and the equivalent for a colon/dash separator.
2. **AC2**: Given page text reproducing the real wrap (`"Chapter 1. Picking an\nInterpreter\n..."`),
   `_openers()`/`r3_heading_sweep` resolves the title as **"Picking an Interpreter"**, not
   `". Picking an"`.
3. **AC3**: A short candidate continuation line that is itself a new chapter opener or a
   TOC section row is **not** appended — the loop must not walk past a genuine boundary.
4. **AC4**: A next line that reads as ordinary body prose (more than 6 words) is **not**
   appended, even when the tail is short — guards against over-absorption swallowing a
   sentence into the "title".
5. **AC5**: The continuation loop is bounded at `_MAX_TITLE_CONTINUATION_LINES` — a
   pathological page (e.g. many consecutive short lines) does not absorb an unbounded
   number of lines into one "title".
6. **AC6**: Existing fixture-based tests (`test_chapter_detection.py`,
   `test_chapter_detection_text.py`) are unchanged and still pass — this story does not
   regress the `toc`/`contents` rungs.

## Scale & Load

1. **Unit of work & range**: one chapter-opener line per detected chapter, per book. A
   book with `N` heading-rung chapters costs at most `N * _MAX_TITLE_CONTINUATION_LINES`
   extra line-comparisons — negligible relative to the page-text sweep this rung already
   performs.
2. **Fixed budgets vs. variable input**: `_TITLE_WORD_TARGET` and
   `_MAX_TITLE_CONTINUATION_LINES` are both new, explicit, fixed constants. Past them, the
   loop simply stops and ships whatever title it has accumulated — never an unbounded
   scan, never a crash. This *is* the silent-degradation risk being fixed, not a new one
   being introduced: the prior behavior silently truncated with no bound-awareness at all.
3. **Scope of the fix**: per-line, per-chapter. No new shared state, no cross-book
   concern.
4. **Unbounded reads/writes**: none — pure in-memory string/regex work, no I/O, matching
   every other rung in this module.
5. **Inherited caps re-derived?**: N/A — new constants, not inherited ones.
6. **Concurrent-request safety**: N/A — `detect_chapters` and its rungs are pure functions
   with no shared mutable state (module docstring: "All pure — no PDF, no DB, no I/O").

## Out of scope

- Font-size-aware extraction (the real structural fix) — deferred to the Sprint 3 docling
  migration, per the existing `r4_font_signals`/D28 precedent.
- The `r1_outline` (`toc`) rung and `r2_contents_page`'s printed-contents-page rows beyond
  the same `CHAPTER_RE` cleanup (AC1's regex fix benefits `r2_contents_page` too, since it
  shares the same `group(2)` capture — but `r2_contents_page`'s own continuation-line
  behavior, if the printed contents page also wraps a title, is not separately re-verified
  here beyond the shared regex fix).
- Re-running detection against the 11 already-generated chapters of the specific book that
  surfaced this — done as a follow-up verification once this fix is deployed, not part of
  the code change itself (chapter titles are not automatically re-detected for existing
  books; a fresh upload or an explicit re-ingestion trigger is required).
