# New Chat Context — Book-Scale Ingestion

**Paste the "Kickoff prompt" section below into a fresh Claude Code session.**
Everything after it is reference material that session can read on demand.

---

## Kickoff prompt

> I'm Dev 1 on TransformED AI. We're starting the **book-scale ingestion** work.
>
> **Read these first, in order:**
> 1. `docs/bmad/book-scale-implementation-brief.md` — the full plan and why
> 2. `docs/book-scale-phase-tracker.md` — the 7 phases and the gate rule
> 3. `CLAUDE.md` — project rules (story-first gate, binding rules, banned libraries)
>
> **The problem:** the code treats one PDF upload as one lesson. The spec (`CLAUDE.md` §9)
> says upload a book once, then generate any chapter on demand. It was built against a
> 41-page sample chapter and every default hardened around that. A 1,000-page book doesn't
> fail — it reports success on ~4% of the content.
>
> **End goal, and the only success criterion:** upload a 1,000-page PDF and have Sprint 1 +
> Sprint 2 run to completion without failing. Nothing else. Sprint 3 starts after Phase 7
> verifies.
>
> **Hard rule — do not break it:** a phase is complete only when tested end to end and
> observed working. `Implemented` is not `Verified`. Phase N+1 doesn't start until Phase N
> is `✅ Verified` and the actual observed numbers are written into the tracker. Never batch
> phases.
>
> **Start with Phase 1** — a spike, no production code, no story file. Run `pypdfium2`'s
> `get_toc()` against 3–4 real textbooks and record chapters detected plus start-page
> accuracy. It gates the shape of Phase 3.
>
> Baseline already measured: *Dive into Deep Learning* (`https://d2l.ai/d2l-en.pdf`, 1,151
> pages) → 27 chapters, 27/27 start pages correct, 4 seconds. Use `apps/api/.venv` —
> `pypdfium2` 4.30.0 is already installed.
>
> Note our repo PDF fixtures all return zero bookmarks because they're script-generated —
> that says nothing about real books, which is exactly why Phase 1 exists.
>
> Report the result and stop. Don't proceed to Phase 2 until I've seen it.

---

## Reference — already verified, do not re-derive

Measured 2026-08-03 in `apps/api/.venv` (`pypdfium2` 4.30.0) against *Dive into Deep
Learning*, 1,151 pages, 44.7 MB.

| Measurement | Result |
|---|---|
| `get_toc()` entries / top-level chapters | 1,335 / **27** |
| Time to read the chapter list | **4 s** |
| Chapter start-page accuracy | **27 / 27** |
| Text extraction, whole book | 7 ms/page → **8.3 s** |
| 300-DPI render | 61 ms/page → 1.2 min |
| **pdfplumber table scan** | **579 ms/page → 11.1 min** (~90% of extraction cost) |
| LLM page-spine fallback, if needed | 57k tokens → **$0.0085** per book |

**The slow part was never reading the PDF** — it was scanning every page for tables, work
chapter detection doesn't need.

### Confirmed absent (greps already run — don't repeat)

- No code anywhere reads the PDF outline/bookmarks (`outline`, `toc`, `bookmark` → zero hits)
- No content hashing or dedup (`sha256`, `hashlib`, `checksum` → zero hits)
- Frontend has no book or chapter concept — only `book_id` in `mocks/data/lessonPackage.ts:5`
- Content router has exactly 3 routes, none mentioning books or chapters
- `chapters` has one INSERT and **zero SELECTs** in the entire backend
- All 10 TODO/FIXME markers lack a `D-nn` register ID

### Key file:line anchors

| What | Where |
|---|---|
| Hardcoded `"chapter_index": 1` | `apps/api/app/modules/content/pipeline/graph.py:624` |
| One-chapter comment (no register ID) | `graph.py:609` |
| Chapter title/pages from `sections[0]`/`[-1]` | `graph.py:610-612` |
| 6,000-char prompt cap (warns at `:1763`) | `graph.py:1751-1770` |
| `structure_max_sections = 15` | `apps/api/app/config.py:301` |
| `_MAX_PHASE1_SECTIONS = 60` | `graph.py:4173` |
| Sections past 60 dropped silently | `graph.py:4243-4254` |
| Graph entry point / topology | `graph.py:4300` / `:4283-4325` |
| `chapters.lesson_id NOT NULL` | `supabase/migrations/20260611000000_initial_schema.sql:132` |
| Extraction signature (no page range) | `nodes/extract_subprocess.py:436-445` |
| Whole-document loop | `nodes/extract_subprocess.py:460` |
| Per-page table scan (the 579 ms) | `nodes/extract_subprocess.py:469` |
| **Page-range primitive that already exists** | `nodes/extract_subprocess.py:144-153` |
| Heading detection | `nodes/structure_detection.py:29` |
| Upload endpoint / 50 MB cap | `modules/content/router.py:242` / `:48` |
| `tier` collected at upload (wrong place) | `modules/content/router.py:255-261` |
| `books.status='ready'` write pattern | `graph.py:914` |
| Eval harness writes success on crash | `apps/api/tests/evals/runner.py:277-316` |

### Three things already exist and were never wired

1. `chapters` already has `book_id`, `page_start`, `page_end`, `chapter_index`
2. `extract_subprocess.py` already computes per-page text, then flattens it away
3. `_build_sub_pdf` is already a page-range primitive

---

## Scope guard

**In scope:** Sprint 1 + Sprint 2 working with a 1,000-page PDF.

**Out of scope** — deferred with `D-nn` IDs, do not pull these in:
splitting the LangGraph into two compiled graphs · cost-tracking split · `progress_pct` ·
`/admin/costs` · storage re-pathing · content-hash dedup · frontend chapter picker ·
RLS re-rooting · session close-out · CES/attention · tutor state machine ·
fallback rungs 2–5 unless Phase 1 says otherwise.

---

## Carry-over items (not for the new session)

1. **Tell Dev 4 about the tutor WebSocket auth gap** — `apps/api/app/modules/tutor/websocket.py:139-146`.
   Anyone who guesses a session ID can drive another student's tutor and read their messages.
   Sprint 3 territory, so it's outside this work, but it's a security defect and shouldn't
   wait for a sprint boundary.
2. **Open PRs still unmerged:** #123 (Sprint 2 + Learner Mode reports), #124 (ADR-001).
   The ADR-002 branch `docs/adr-002-book-scale-ingestion` is pushed with no PR opened.
3. **Untracked in the working tree:** `docs$name.pdf`, `learning-docs/CONTEXT-NEW-CHAT-SPRINT2.md`.
