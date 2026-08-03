# Phase 1 Spike — Chapter Detection via `pypdfium2.get_toc()`

**Owner:** Dev 1
**Run on:** 2026-08-03
**Type:** Spike. No production code, no story file (per `docs/bmad/book-scale-implementation-brief.md` §5).
**Tracker:** `docs/book-scale-phase-tracker.md` → Phase 1
**Environment:** `apps/api/.venv`, Python 3.13.4, `pypdfium2` 4.30.0, Windows 11

Scripts are spike-only and were **not** committed to the repo (scratchpad:
`toc_spike.py`, `nobookmark_probe.py`).

---

## 1. What was measured

For each real textbook:

1. Is a bookmark tree present, and how long does `get_toc()` take?
2. Per outline level: entry count, median/min/max page span, monotonicity.
3. Which level the prototyped heuristic selects — *coarsest level with 4–80 entries
   and median span ≥ 3 pages*.
4. **Start-page accuracy** — open each detected chapter's start page, read the first
   400 characters, and confirm the chapter title appears there.
   *strict* = exact start page. *lenient* = start page ±1.
   Title match = normalised substring, or ≥70 % of significant title words present.

For books with **no** bookmark tree, a second probe measured what a fallback rung
would actually have to work with: text-layer density per page, presence of a printed
contents page, and whether chapter openers lead with a recognisable heading.

---

## 2. Books with a bookmark tree — 5 of 8

| Book | Pages | TOC entries | `get_toc()` | Level chosen | Chapters | Start page strict | lenient ±1 | Median chapter |
|---|---:|---:|---:|:--:|---:|:--:|:--:|---:|
| Dive into Deep Learning (baseline) | 1,151 | 1,335 | 1.76 s | 0 | 27 | **27/27** | 27/27 | 40 p |
| OpenStax College Physics 2e | 1,671 | 525 | 0.03 s | 0 | 42 | **42/42** | 42/42 | 44 p |
| OpenStax Biology 2e | 1,475 | 591 | 0.05 s | 0 | 53 | **53/53** | 53/53 | 28 p |
| Mathematics for Machine Learning | 417 | 104 | 0.06 s | 1 | 20 | 19/20 | 20/20 | 22 p |
| Think Python 2e | 244 | 240 | 0.04 s | 0 | 22 | **22/22** | 22/22 | 10 p |
| **Total** | | | | | **164** | **163/164 (99.4 %)** | **164/164 (100 %)** | |

The single strict miss is *Mathematics for Machine Learning* entry `[8] "Exercises"`
— the bookmark points one page early; the title is found on start page +1. It is a
non-content entry (see §4), so it would be filtered out anyway.

**Level-selection heuristic: correct on 5 of 5, no manual override needed.**
It chose level 0 on four books and level 1 on *Mathematics for Machine Learning*,
whose level 0 holds only 3 "Part" entries with a median span of 163 pages. All chosen
levels were monotonic in page order — page ranges are ascending and non-overlapping,
which Phases 3 and 4 depend on.

**Baseline reproduced exactly:** *Dive into Deep Learning* → 27 chapters, 27/27 start
pages correct. `get_toc()` measured at 1.76 s here vs. the 4 s recorded in the brief.

---

## 3. Books with **no** bookmark tree — 3 of 8

All three are NCERT Indian school physics textbooks — **the primary target segment**.

| Book | Pages | TOC entries | Text layer (median chars/page) | Printed contents page | In-body `CHAPTER N` openers |
|---|---:|---:|---:|:--:|---:|
| NCERT Class XI Physics Part 1 (2025-26) | 184 | **0** | 2,738 | yes | 7 true (+1 false) |
| NCERT Class XI Physics Part 2 (2006 ed.) | 189 | **0** | 2,816 | yes | 7 true, ch 9–15 (+4 false) |
| NCERT Class XII Physics Part 1 | 291 | **0** | 2,296 | yes, well structured | 0 |

Two facts materially change the fallback cost:

**None of them is a scan.** All three carry a born-digital text layer at
~2,300–2,800 chars/page, with 1–9 near-empty pages out of ~200. **No OCR and no
vision model is required** for these books — the risk recorded in the brief §8
("scanned books carry no font metadata at all") does not apply to this sample.

**The two available fallback signals are complementary.** Where the in-body heading
sweep works, it is clean:

```
NCERT XI Part 1        NCERT XI Part 2
p  16  CHAPTER ONE     p  11  CHAPTER NINE
p  28  CHAPTER TWO     p  26  CHAPTER TEN
p  42  CHAPTER THREE   p  54  CHAPTER ELEVEN
p  64  CHAPTER FOUR    p  78  CHAPTER TWELVE
p  86  CHAPTER FIVE    p  98  CHAPTER THIRTEEN
p 107  CHAPTER SIX     p 116  CHAPTER FOURTEEN
p 142  CHAPTER SEVEN   p 143  CHAPTER FIFTEEN
```

Where it fails — Class XII Part 1, 0 in-body hits — the printed contents page is
almost machine-readable already:

```
CONTENTS
FOREWORD v
PREFACE xi
CHAPTER ONE
ELECTRIC CHARGES AND FIELDS
1.1 Introduction 1
1.2 Electric Charges 1
...
CHAPTER TWO
ELECTROSTATIC POTENTIAL AND CAPACITANCE
2.1 Introduction 51
```

So on this sample, **every** book without bookmarks yields at least one of the two
signals, and neither signal needs a model to extract.

### Two problems the fallback will have to solve

1. **Printed page numbers are not PDF page indices.** The contents page says
   "Chapter 2 … 51"; front matter means that is not PDF page 51. An offset must be
   derived, not assumed. This is new Phase 3 design work.
2. **False positives sit in back matter.** The heading sweep hit answer keys and
   appendices (`p 175 Chapter 1`, `p 186 CHAPTER 9`) — i.e. pages *referencing* a
   chapter rather than opening one. Detected starts must be monotonic and
   de-duplicated by chapter number, not accepted in document order.

---

## 4. Cross-cutting finding — non-content entries

The chapter counts above include front and back matter that the outline lists as
peers of real chapters:

| Book | Entries at chosen level | Actual teachable chapters | Non-content |
|---|---:|---:|---|
| OpenStax Biology 2e | 53 | 47 | Contents, Preface, Appendix A/B/C, Index |
| OpenStax College Physics 2e | 42 | 34 | Contents, Preface, Appendix A–D, Answer Key, Index |
| Dive into Deep Learning | 27 | 22 | Preface, Installation, Notation, Appendix A/B, References |
| Math for Machine Learning | 20 | 12 | 6× "Exercises", References, Index |
| Think Python 2e | 22 | 21 | Preface |

Left unfiltered, a student's chapter picker would offer "Index" and "Answer Key" as
lessons. This is cheap to fix (title blocklist + a minimum page-span floor) but it is
**not currently in the Phase 3 or Phase 6 work lists** and should be added.

---

## 5. Chapter size — the brief's core premise holds

Median detected chapter size across all books: **10–44 pages**, against a pipeline
built and validated at 41 pages (`demo-assets/sample-chapter.pdf`).

| Book | Median | Min | Max |
|---|---:|---:|---:|
| OpenStax College Physics 2e | 44 p | 4 p | 62 p |
| Dive into Deep Learning | 40 p | 3 p | 138 p |
| OpenStax Biology 2e | 28 p | 2 p | 56 p |
| Math for Machine Learning | 22 p | 2 p | 50 p |
| Think Python 2e | 10 p | 6 p | 22 p |

The brief's claim — *"feed it one chapter and every existing default becomes correct
again"* — is supported. Two outliers to note: D2L's Appendix A is 138 pages, and
several chapters are 2–4 pages. Phase 5 should not assume a chapter is always ~40 pages.

---

## 6. Decision

The tracker's rule was: ≥3 of 4 books yield a usable list → proceed to Phase 2 as
planned; <3 of 4 → add rungs 2–5 and re-plan before writing code.

The result does not fall cleanly on either side, and the split is not random:

- **Rung 1 works, and works very well, where it applies.** 5 of 8 books, 164 chapters,
  99.4 % strict start-page accuracy, worst case 1.76 s. It needs no change.
- **Rung 1 alone covers 0 % of the Indian school-textbook sample** — the segment the
  product is actually for. That is not a marginal miss; it is a whole market segment.

So: **proceed with rung 1 exactly as designed, and treat rungs 2 and 3 as required
Phase 3 scope rather than contingency.** Concretely, `boundary_confidence` must be
able to take a value meaning "derived from a printed contents page", which the Phase 2
enum (`toc` | `font` | `fallback`) already accommodates.

The cost of that added scope is lower than the brief assumed, because the fallback
books are born-digital: no OCR, no vision model, and the ~$0.0085/book LLM page-spine
check stays a rung-4 backstop rather than a necessity.

**Rungs 4 and 5 remain deferred** — nothing in this sample required them.

---

## 7. What this does not cover

- No genuinely scanned (image-only) textbook was tested. NCERT's own distribution is
  born-digital; a photocopied or camera-scanned upload remains unmeasured, and that is
  where rung 4 would earn its place.
- NCERT distributes most of its catalogue as **one PDF per chapter**, not one per book
  (confirmed: `ncert-keph1` ships `keph101.pdf` … `keph108.pdf`). A single-chapter
  upload must therefore stay a first-class case — it is the common shape for this
  segment, not a degenerate one.
- Publisher textbooks (Pearson, McGraw-Hill) could not be tested legally.
