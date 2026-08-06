# Story {{epic_num}}.{{story_num}}: {{story_title}}

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a {{role}},
I want {{action}},
so that {{benefit}}.

## Acceptance Criteria

1. [Add acceptance criteria from epics/PRD]

## Scale & Load

<!-- REQUIRED SECTION — see docs/SCALE-CONTRACT.md. Answer all six BEFORE writing Tasks/Subtasks:
     the answers change the Acceptance Criteria above. A story that reaches dev-story with any
     `[ANSWER REQUIRED]` marker still present is incomplete and goes back.
     "N/A" is a valid answer ONLY with a reason on the same line. A bare "N/A" is a missing answer.
     The one-line test: "What input makes this silently wrong rather than loudly broken?" -->

1. **What is ONE unit of work, and what is its range?**
   `[ANSWER REQUIRED]`
   <!-- Hint: name the unit (one chapter? one book? one request?), then min / typical / largest
        actually MEASURED / behaviour beyond it. The unit was silently "one PDF" when it should
        have been "one chapter": a 1,151-page book became one lesson built from 90,000 characters
        — 4% of it — and nothing errored. -->

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   `[ANSWER REQUIRED]`
   <!-- Hint: list every cap that meets a variable input — token windows, section counts, char
        limits, page counts, byte sizes, timeouts, retry counts. For each, behaviour past the limit
        must be an explicit error or an explicit, SURFACED degradation. Silent truncation is never
        an acceptable answer. `structure_max_sections = 15` × `_get_section_body(max_chars=6000)`
        = ~90,000 chars ≈ 36 pages of LLM-visible window regardless of input size; the $3.00/lesson
        ceiling never fired because the failure was cheap, not expensive. -->

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   `[ANSWER REQUIRED]`
   <!-- Hint: name the scope explicitly for each limit. Unstated scope is a limit that is wrong on
        the second user or the second replica. D52 — the rate limiter fell back to keying by IP, so
        every authenticated user shared one bucket. D49 — `RATE_LIMIT_STORAGE_URL` defaults to
        `memory://`, so every ceiling silently multiplies by replica count. -->

4. **Which reads and writes are UNBOUNDED?**
   `[ANSWER REQUIRED]`
   <!-- Hint: every query carries `.limit()`/`.range()`, uses an exact `count=` instead of
        materialising rows, or states why the row count is naturally bounded (`# BOUNDED:`).
        The concurrency gate did `select("lesson_id")` over EVERY `generating` row to count them;
        the chapters→lessons embed had no limit, so a chapter regenerated 20 times returned 20 rows
        to every chapter-list request. D50 — 300-DPI render + image upload had no count cap at all.
        Guarded by `tests/unit/test_unbounded_queries.py`. -->

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   `[ANSWER REQUIRED]`
   <!-- Hint: when the unit of work changes, every cap sized against the OLD unit is unjustified
        until re-derived — list them and show the new arithmetic. The 50 MB upload cap was sized
        when one upload was one lesson; never revisited when the unit became a book, so OpenStax
        Physics (1,671 pages, 251 MB) and Biology (1,475 pages, 382 MB) cannot be ingested at all.
        Both are exactly the target use case. -->

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   `[ANSWER REQUIRED]`
   <!-- Hint: for each, say what happens when N requests arrive simultaneously. If the answer
        relies on a read followed by a write with no lock or DB constraint between them, say so and
        bound the damage. The per-user concurrency cap counts `generating` lessons then inserts with
        nothing in between — three concurrent requests all see the same count and all insert. D45 —
        the `(chapter_id, tier)` idempotency pre-check is the same shape, with no UNIQUE constraint
        anywhere to fall back on, so concurrent duplicates both bill. -->

## Tasks / Subtasks

- [ ] Task 1 (AC: #)
  - [ ] Subtask 1.1
- [ ] Task 2 (AC: #)
  - [ ] Subtask 2.1

## Dev Notes

- Relevant architecture patterns and constraints
- Source tree components to touch
- Testing standards summary

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
- Detected conflicts or variances (with rationale)

### References

- Cite all technical details with source paths and sections, e.g. [Source: docs/<file>.md#Section]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
