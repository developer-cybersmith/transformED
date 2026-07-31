# ADR-002 — Book-scale ingestion and per-chapter lesson generation

**Status:** 🔴 **PROPOSED — this is a real architecture gap, not a tuning problem**
**Date:** 2026-07-30 · **Owner:** Dev 1 · **Trigger:** *"we need to upload a 1,000-page PDF and run it through extraction, lesson package generation, and Learner Mode"*

---

## 1. The short answer

**You cannot do this today, and raising the timeouts will not fix it.**

Raising `EXTRACT_TIMEOUT_CAP_S` and `ARQ_JOB_TIMEOUT_S` — the obvious move, and the one Sprint 1
used — gets a 1,000-page book *ingested*. It does **not** get you usable lessons, because a
whole-book run produces **one lesson built from 3.6% of the book**.

The root cause is that **Phase A (ingestion) and Phase B (generation) are welded together in
three independent places**, while `CLAUDE.md` specifies them as separate phases with different
cardinality:

> **Phase A — Book Ingestion** (once per book, ~2–5 min)
> **Phase B — Chapter Generation** (**per chapter**, student-triggered, ~5–15 min)
> *"Hierarchical document processing — process Chapter → Section → Topic. **Never full-book single call.**"*

The code implements *one PDF = one lesson*. The architecture calls for *one book = many chapters
= many lessons*. **Everything below follows from that single divergence.**

---

## 2. The three fusions (all verified in code)

### 2a. Schema fusion — a chapter cannot exist without a lesson

```sql
-- supabase/migrations/20260611000000_initial_schema.sql:129-138
CREATE TABLE public.chapters (
  chapter_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id     uuid NOT NULL,
  lesson_id   uuid NOT NULL REFERENCES public.lessons(lesson_id) ON DELETE CASCADE,  -- ← the blocker
  ...
);
```

`chapters.lesson_id` is **NOT NULL**. `chunks.chapter_id` then references `chapters`
(`:145-147`). So the dependency chain is:

```
lesson  ──(required)──>  chapter  ──(required)──>  chunks  ──>  embeddings
```

**You cannot ingest a book without generating a lesson.** Ingestion is not separable at the data
layer, which is the opposite of what Phase A/B requires.

### 2b. Graph fusion — there is no exit after ingestion

```python
# graph.py:4300-4325
graph.set_entry_point("extract")
graph.add_edge("extract", "structure")
graph.add_edge("structure", "chunk")
graph.add_edge("chunk", "embed")
graph.add_conditional_edges("embed", _fan_out_phase1_economy_nodes, _ECONOMY_NODES)   # ← unconditional in practice
...
graph.add_edge("package_builder", END)
```

One linear chain. The edge out of `embed` always fans into generation. **There is no way to run
ingestion alone**, and no state on which a conditional exit is currently keyed.

### 2c. Job fusion — one ARQ job, one budget, for both phases

`content_pipeline_job` runs the whole graph under a single `arq_job_timeout_s = 1800`. Phase A
for a book was **measured at 66 min (3,960s)** in Sprint 1 — 2.2× that budget before Phase B has
begun.

### 2d. And chapter splitting was never implemented

```python
# graph.py:609-626 — chunk_node
# ── Create one chapter row (one chapter per lesson ingestion in MVP) ──────
chapter_title = sections[0].get("title", "Chapter") if sections else "Chapter"
...
"chapter_index": 1,
```

**Exactly one chapter row, hardcoded `chapter_index: 1`**, titled after the first section. A
1,000-page book becomes a single "chapter".

### 2e. The schema was *already* migrating toward books — and stopped halfway

`20260625000000_chunks_inline_embedding.sql` did:

1. create the `books` table (**with its own `status: processing|ready|failed` lifecycle** —
   exactly what book-level ingestion needs)
2. FK `chapters.book_id → books.book_id`
3. add `lessons.book_id` **nullable**, `ON DELETE SET NULL` — *"lesson survives book deletion"*
4. add `book_id` to `chunks` and backfill it

**Points 3 and 4 only make sense in a world where books and lessons are independent.** That work
was started and never finished — `chapters.lesson_id NOT NULL` is the leftover that blocks it.

---

## 3. The reframe — splitting by chapter makes the existing caps *correct*

The 6,000-char-per-section prompt cap (`graph.py:1751`) and `structure_max_sections = 15` give a
**90,000-character total LLM budget per lesson**. That budget is not wrong; it is being asked to
cover the wrong unit of content.

| Chapters | Pages/chapter | Chars/chapter | LLM budget | **Coverage** |
|---|---|---|---|---|
| **1** | 1000 | 2,500,000 | 90,000 | **3.6%** ← today |
| 10 | 100 | 250,000 | 90,000 | 36.0% |
| 20 | 50 | 125,000 | 90,000 | 72.0% |
| **30** | **33** | **83,333** | **90,000** | **100%** |
| 40 | 25 | 62,500 | 90,000 | 100% |

**A typical textbook has 20–40 chapters.** At that granularity the pipeline's existing budget
covers the content completely. This was measured, not assumed: the real 41-page
`sample-chapter.pdf` produces 8 sections and lands at **~88% coverage** — while the same caps
applied to a 120-page uniform document give **4%**.

**So the fix is not "raise the caps." It is "feed it chapters."** The caps were designed for the
unit the PRD specifies, and they work for it.

### Economics of the split design

| | |
|---|---|
| Ingest a 1,000-page book | **once**, ~66 min, **~$0.014** (embeddings only) |
| Generate one chapter lesson | ~5–15 min, **~$0.42** (student-triggered, on demand) |
| If every chapter were generated | 30 × $0.42 = **$12.60** — but nobody does this; it is on demand |
| Per-lesson ceiling | $3.00 — **86% headroom** at the estimated $0.42 |

Ingestion becomes cheap and rare. Generation stays per-lesson, on demand, and comfortably inside
the ceiling. **This is what the PRD's cost model always assumed.**

---

## 4. Target architecture

```
POST /api/content/books        (new)     ── upload PDF, create books row (status=processing)
   └─ ARQ job: ingest_book                  long budget (5400s+)
        extract → structure → SPLIT INTO N CHAPTERS
                → per chapter: chunk → embed
        → books.status = 'ready'
        NO lesson created

GET  /api/content/books/{id}/chapters  (new)  ── student picks a chapter

POST /api/content/lessons      (changed) ── { book_id, chapter_id, tier }   ← not a PDF
   └─ ARQ job: generate_lesson              existing 1800s budget
        load that chapter's sections/chunks
        → Phase-1 fan-out → planner → slides → tts → images → package_builder
        → one LessonPackage, Learner Mode tier applied per chapter
```

**Learner Mode is unaffected and gets *better*.** Tier already drives per-lesson slide budgets
(20–25 / 12–15 / 6–8) and quiz bands (3–5 / 2–3 / 1–2). Applied per *chapter* those numbers are
sensible; applied to a whole book they are absurd — 25 slides for 1,000 pages. **The tier bands
are further evidence the system was designed per chapter.**

The existing upload path should be **kept** for the single-chapter case (upload a chapter PDF →
one lesson). It is the demo path and it works.

---

## 5. What must change, in dependency order

| # | Change | Owner | Effort | Notes |
|---|---|---|---|---|
| **1** | **Fix D28 — chapter detection.** `detect_headings` populates candidates keyed by text with `if text not in candidates`, so the **font strategy always beats the regex**. `_CHAPTER_RE` (`structure_detection.py:26`) matches `Chapter\s+\d+[.:]` correctly but **never gets to apply** if the font pass already claimed that text. Result: chapters are currently labelled `topic` and rank *below* their own subsections. | Dev 1 | days | **PREREQUISITE.** Chapter splitting is only as good as chapter detection. D28 was parked for Sprint 3 as a nicety; it is now on the critical path. |
| **2** | **Migration: `chapters.lesson_id` → NULLABLE.** Chapters belong to books. Lessons reference chapters, not the reverse. | Dev 1 | hours | ⚠️ **§16 frozen-contract change — requires four-dev review.** New migration only; never modify an applied one. |
| **3** | **Split the graph in two.** `ingest_graph` (extract→structure→split→chunk→embed) and `generate_graph` (fan-out→…→package_builder), sharing the same node functions. | Dev 1 | days | Cleaner than a conditional exit; gives each phase its own checkpoint namespace. |
| **4** | **Two ARQ jobs with separate budgets.** `ingest_book_job` (5400s+) and `generate_lesson_job` (1800s, unchanged). | Dev 1 | hours | Removes the 1800s-covers-everything conflict. |
| **5** | **Real chapter splitting in `chunk_node`.** Replace the hardcoded single chapter with N rows from detected chapter boundaries, `chapter_index` sequential, `page_start`/`page_end` real. | Dev 1 | days | Depends on 1 and 2. |
| **6** | **Incremental extract checkpointing.** Extract writes its checkpoint **only on success** (`graph.py:400-421`), and `max_tries = 3` — so a book that times out re-downloads and re-extracts from zero, three times. **75 minutes of burned worker slot for nothing.** | Dev 1 | days | Independent; worth doing regardless. |
| **7** | **New endpoints** — `POST /books`, `GET /books/{id}/chapters`; change `POST /lessons` to accept `{book_id, chapter_id, tier}`. | Dev 1 | days | ⚠️ **API contract change — Dev 2 must build chapter selection.** |
| **8** | **Upload limit.** `MAX_PDF_SIZE_BYTES = 50 MB` (`content/router.py:48`). Sprint 1's book was 46.7 MB — *barely* under. Decide: raise it, or add resumable/chunked upload. | Dev 1 | hours–days | A 60 MB book is rejected at the door today. |
| **9** | **Frontend: chapter picker.** A book is no longer one lesson; the student chooses a chapter. | **Dev 2** | days | Net-new UI. Dev 2 already has 18 unstarted tasks. |

---

## 6. Risks and unknowns

- **D28 is load-bearing and its difficulty is unknown.** If chapter detection cannot be made
  reliable on real textbooks (varied fonts, scanned pages with no font metadata at all, and the
  120-page fixture that yields **zero headings from 3,000 font spans**), chapter splitting has no
  foundation. **This is the biggest risk in the plan** and should be spiked first.
  Sprint 3's planned docling document-AI migration is the strategic answer; it is not built.
- **Scanned books have no font metadata**, so only the regex survives — and the regex only
  catches `Chapter N` / `N. Title` forms. A book without those patterns cannot be split at all.
  **A manual chapter-boundary override may be unavoidable.**
- **§16 gate on the migration** means schedule dependency on three other developers.
- **Phase B has still never run live**, so the ~$0.42/lesson and 5–15 min figures are estimates.
  Splitting does not change that; it makes it more urgent, since the per-chapter numbers are the
  ones the whole cost model rests on.
- **Nothing here is small.** Realistically **1–2 weeks** of Dev 1 work plus Dev 2's UI, plus a
  four-dev review, plus a D28 spike of unknown length.

---

## 7. Recommendation

**Do not raise the timeouts and call it done.** That produces a book-shaped lesson covering 3.6%
of the book — a result that *looks* like success (status `ready`, a valid package, no errors) and
is a product failure. Given this project's history, a silent 96% content loss with a green status
is exactly the failure mode that survives longest.

**Sequence:**

1. **Spike D28 first** — one day, on 3–4 real textbook PDFs. Can we reliably detect chapter
   boundaries? **Everything else depends on the answer, and it may be No.**
2. **In parallel, run one live Phase B on a single chapter.** It is the cheapest way to validate
   the per-chapter numbers this whole ADR rests on, and it unblocks six other tracker items.
3. **Only then** commit to the migration and the graph split.

**Interim, if a book must be demoed this week:** ingest with `EXTRACT_TIMEOUT_CAP_S=5400` /
`ARQ_JOB_TIMEOUT_S=5700` (Sprint 1's proven values) to populate chunks and embeddings, then
generate lessons from **individual chapter PDFs** split outside the system. That demonstrates
both halves honestly without pretending the fused path works at book scale.

---

## Appendix — evidence

| Claim | Verify at |
|---|---|
| `chapters.lesson_id NOT NULL` | `supabase/migrations/20260611000000_initial_schema.sql:129-138` |
| `chunks.chapter_id` FK | same file, `:145-147` |
| `books` table + status lifecycle | `20260625000000_chunks_inline_embedding.sql:28-37` |
| `lessons.book_id` nullable, book/lesson independence intended | same file, header `:7-12` |
| Linear graph, no ingestion exit | `graph.py:4283-4325` |
| One hardcoded chapter | `graph.py:609-626` |
| 6,000-char prompt cap | `graph.py:1751-1770` |
| `structure_max_sections = 15` | `app/config.py` |
| Extract timeout formula | `graph.py:183-204` (`page_estimate = bytes // 30_000`) |
| `arq_job_timeout_s=1800`, `extract_timeout_cap_s=1500`, `max_tries=3` | `app/config.py`, `app/workers/main.py:128` |
| Extract checkpoints only on success | `graph.py:400-421` |
| 50 MB upload gate | `app/modules/content/router.py:48` |
| Chapter regex | `nodes/structure_detection.py:26` |
| D28 (font beats regex) | `docs/DEFECT-REGISTER.md` → D28; `nodes/structure_detection.py` `if text not in candidates` |
| Sprint 1 book run: 66 min, needed 5400/5700 | `docs/stories/2-0b-page-scoped-docling.md` |
| Measured coverage (41p → 88%, 120p → 4%) | this ADR §3, reproduced 2026-07-30 |
