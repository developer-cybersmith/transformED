# The Scale Contract

**Binding on every story, every PR, every review. No exceptions.**
Established 2026-08-05, after an entire unplanned sprint (book-scale, Phases 1–7) existed only
to retrofit scale into work that was built without it.

---

## Why this exists

Sprints 1 and 2 and Learner Mode were all built, reviewed and merged green. Every one of them
worked — on a small PDF, for one user, on one instance. None of that was written down as an
assumption, so none of it was ever checked.

The result was not a slow system. It was a system that **reported success while being wrong**:

> A 1,000-page textbook uploaded fine, processed fine, and produced a lesson.
> The lesson covered **4 % of the book**. Nothing errored. Nothing warned.
> The `$3.00/lesson` cost ceiling never fired, because the failure was *cheap*, not expensive.

That is the signature failure of missing scale constraints, and it is why this document is not
advice. **A story that does not answer the six questions below is incomplete and must be sent
back.** Prose guidance does not hold in this codebase — see the register's Part 1 — so each
question below carries an enforcement mechanism, not just an instruction.

---

## The six questions

Every story answers all six, in a `## Scale & Load` section. "N/A" is a valid answer **only with
a reason**; a bare "N/A" is a missing answer.

### 1. What is ONE unit of work, and what is its range?

State the min, the typical, the largest you have actually measured, and what happens beyond it.

> **What this prevents.** The unit was silently "one PDF" when it should have been "one chapter".
> Nobody wrote it down, so nobody noticed it was wrong. A 1,151-page book became one lesson built
> from 90,000 characters — 4 % — and the entire book-scale sprint existed to undo that.

### 2. Which budgets are FIXED while the input VARIES — and what happens when input exceeds them?

List every fixed cap that meets a variable input: token windows, section counts, character
limits, page counts, byte sizes, timeouts, retry counts.

For each, the behaviour past the limit must be **an explicit error** or **an explicit, surfaced
degradation**. **Silent truncation is never an acceptable answer.**

> **What this prevents.** `structure_max_sections = 15` × `_get_section_body(max_chars=6000)`
> means ~90,000 characters is the entire LLM-visible window **regardless of input size**. At
> ~2,500 chars/page that is ~36 pages. Feed it 1,151 pages and it silently uses 3 % — emitting a
> `logger.warning` nobody reads. The cost ceiling cannot catch this: the failure is a *cheap
> wrong* answer, not an expensive one.

### 3. What is the SCOPE of every limit — per user, per instance, or per deployment?

Name it explicitly for each limit. A limit whose scope is unstated is a limit that is wrong on
the second instance or the second user.

> **What this prevents.** Two real defects, both invisible in single-user testing:
> **D52** — the rate limiter fell back to keying by **IP**, so every authenticated user shared
> one bucket and one caller could lock out everyone behind the same egress IP.
> **D49** — `RATE_LIMIT_STORAGE_URL` defaults to `memory://`, so every ceiling silently
> multiplies by replica count.

### 4. Which reads and writes are UNBOUNDED?

Every query must carry a `.limit()` / `.range()`, use an exact count instead of materialising
rows, or state in a comment why the row count is naturally bounded.

> **What this prevents.** The per-user concurrency gate did `select("lesson_id")` over **every**
> `generating` row to count them. The chapters→lessons embed had no limit, so a chapter
> regenerated 20 times returned 20 rows to every chapter-list request. **D50** — 300-DPI page
> rendering and image upload had no count cap at all, and sat entirely outside `cost_tracker`.

### 5. Which caps were INHERITED from an earlier design, and have they been re-derived?

When the unit of work changes, every cap sized against the old unit is now unjustified until
re-derived. List them and show the new arithmetic.

> **What this prevents.** The **50 MB upload cap** was sized when one upload was one lesson. It
> was never revisited when the unit became a book — so **OpenStax Physics (1,671 pages, 251 MB)
> and Biology (1,475 pages, 382 MB) cannot be ingested at all**. Both are exactly the target use
> case. Chapter detection handles them perfectly; no student can ever get that far.

### 6. Is every check-then-act sequence safe under CONCURRENT requests?

For each: what happens when N requests arrive simultaneously? If the answer relies on a read
followed by a write with no lock or constraint between them, say so and bound the damage.

> **What this prevents.** The per-user concurrency cap counts `generating` lessons and then
> inserts, with nothing in between — three concurrent requests all see the same count and all
> insert. **D45** — the `(chapter_id, tier)` idempotency pre-check is the same shape, and there
> is no UNIQUE constraint anywhere to fall back on, so concurrent duplicates both bill.

---

## Enforcement — because prose does not hold

| Where | Mechanism |
|---|---|
| **Story creation** | `## Scale & Load` is a **required section** of the story template. A story missing it is incomplete and goes back. |
| **Code review** | A **sixth mandatory review layer: Scale & Load**. See CLAUDE.md's review gate. |
| **CI** | `tests/unit/test_unbounded_queries.py` — a source scan failing on any Supabase `.select()` reachable from a request path with no `.limit()`, `.range()`, `count=`, or `# BOUNDED:` justification. |
| **Register** | Binding rule 8. Any scale limitation shipped knowingly needs a `D-nn` ID, an owner and a trigger — same as every other documented limitation. |

## The one-line test

Before merging, ask: **"What input makes this silently wrong rather than loudly broken?"**

If you cannot answer, you have not finished the story. Every defect this project has found —
without exception — was something that reported success without being checked.
