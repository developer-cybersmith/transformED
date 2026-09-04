# Story 4-28 (Phase 2, P2-1) — Tutor Q&A: real backend (RAG + LLM_TUTOR)

Status: draft

## Story

As Dev 4 (picking this up — Dev 2's scoping email named the WS/FSM/rate-limiting pieces as my
call specifically; D149's proposed endpoint owner was "TBD/Dev 3," never actually started),
I want a real backend behind the "Ask Tutor" button that already ships in production
(`AskTutorPanel.tsx`, Story 2-57/BR-5, D149) — one that retrieves relevant book content, asks
`LLM_TUTOR` a grounded question, and returns a real answer instead of "noted, no answer yet" —
so that a student who pauses to ask a question mid-lesson gets a real, grounded response bounded
by an explicit per-session cap, not silence and not an unbounded LLM bill.

## Background

- **D149** (`docs/DEFECT-REGISTER.md`): "Not a defect — a documented, deliberately-scoped gap."
  `AskTutorPanel.tsx` + `submitTutorQuestion()` (`apps/web/src/lib/assessment.ts`) are real,
  shipped, and 100% mocked — `submitTutorQuestion()` returns `Promise.resolve({received: true})`
  and never calls `api.post(...)` at all. **Confirmed by grep before starting this story**: no
  route registers `POST /api/assessment/...questions` or any equivalent anywhere in the backend.
  Nobody has started this — confirmed directly with Dev 2 the same day this story was written.
- **CLAUDE.md** already reserves the pieces this story needs: `LLM_TUTOR` env var
  (`settings.llm_tutor`, default `gpt-4o`, already defined in `config.py` — unused until now),
  and an explicit carve-out from two otherwise-locked rules: *"Phase 2 RAG tutor embeds student
  questions at query time — this is permitted"* (the one exception to "chunk embeddings at
  ingestion only") and this story's LLM call is a deliberate, new exception to "no GPT call at
  intervention time" (that rule was written for pre-generated interventions specifically, per
  CLAUDE.md's Tutor State Machine section — not this).
- **Retrieval side already exists.** Every book's chunks are already embedded (pgvector,
  `chunks.embedding vector(1536)`, HNSW index) at ingestion by Dev 1's content pipeline. Nothing
  needs re-embedding — only the student's question gets embedded, at ask-time, via the existing
  `OpenAIEmbeddingsProvider` (`apps/api/app/providers/embeddings/openai.py`).
- **FSM impact — investigated, not assumed: none needed.** Read `process_attention_signal`
  (`apps/api/app/modules/tutor/service.py`) directly: the fatigue-trigger block (S3-45/D7) and
  the CES-window computation both only execute *inside the handler an incoming `attention_signal`
  message triggers* — there is no background timer. `AskTutorPanel`'s pause (`pauseReason:
  'intervention'` in `player.machine`) already stops the frontend from sending `attention_signal`
  while open (same mechanism as every other pause — manual, slide-transition — per Story 2-57's
  own "every existing pause-gated effect needed zero changes"). No signal in flight while a
  student types a question means the fatigue/CES code path simply never runs during that window
  — CES monitoring is suspended without ever leaving `TEACHING`, for free, with no FSM change.
  This confirms (not merely repeats) the architecture Dev 2 and I discussed by email: no new FSM
  state, no `graph.py` change.
- **Path correction.** D149's originally-proposed contract used `POST
  /api/assessment/sessions/{session_id}/questions` (plural "sessions"). The actual, already-shipped
  convention in this router is singular: `POST /assessment/session/{session_id}/complete`, `GET
  /assessment/session/{session_id}/report`. This story uses `POST
  /assessment/session/{session_id}/questions`, matching the real convention, not the originally
  proposed (and never-implemented, never-verified-against-code) path.

## Explicitly out of scope for this story (named, not silently dropped)

- **Frontend wiring.** `submitTutorQuestion()`'s call site (`AskTutorPanel.tsx`) is documented to
  need zero changes when the stub is swapped for a real call — only the function body does, per
  its own D149 comment. This story defines and ships the real response shape
  (`SubmitTutorQuestionResult` gains `answer: string | null` + `declined: bool`) but does **not**
  wire the frontend to call the real endpoint or render the answer — that is a frontend
  change (Dev 2's domain) with its own small UI decision (how to show a real answer vs. today's
  static "noted" card), tracked as a named follow-up, not silently assumed.
- **WebSocket / streaming delivery.** Dev 2's email offered "REST-for-now-WS-later or go straight
  to WS" as my call. REST wins for *this* story on a practical constraint, not a reversal of the
  architecture opinion I gave by email (I still think WS is the better end state): a new WS
  message type requires a 4-dev PR against the frozen `packages/shared/types/ws.ts` contract, and
  no such review can happen inside this session. Shipping a real, working REST answer now — using
  the exact REST shape the frontend stub already assumes — is strictly better than blocking on a
  contract review nobody can hold today. Named as a real V2, not silently dropped.
- **A new dedicated cost-ceiling subsystem.** Bounded instead via two existing-pattern mechanisms
  (Task 3): a per-session question-count cap (Redis `INCR`+`EXPIRE`, the exact pattern
  `segment_index` already uses) and a `max_tokens` cap on the completion call. See Scale & Load
  Q2 for why this is sufficient without inventing new cost-tracking machinery.

## Acceptance Criteria

1. `POST /assessment/session/{session_id}/questions` (new endpoint, `apps/api/app/modules/
   assessment/router.py` + `service.py`) validates session ownership (JWT `sub` == `sessions.
   user_id`, matching `grade_quiz`'s existing IDOR-guard pattern exactly) and returns `404`/`403`
   on the same conditions `grade_quiz` already does for a missing/foreign session.
2. The per-session question count is checked and incremented atomically enough that two
   concurrent requests can't both slip through at the cap boundary (Scale & Load Q6) — past the
   cap, the endpoint returns a clear, explicit degrade (a real, non-empty message telling the
   student they've reached this session's question limit) with **no LLM/embedding call made**,
   never a silent drop and never an unbounded allowance.
3. The student's question is embedded at query time (`OpenAIEmbeddingsProvider.embed_texts`, one
   text) and used for a pgvector cosine-similarity search against `chunks`, scoped to the
   session's lesson → `chapter_id` (falling back to `book_id` if `chapter_id` is null), top-K
   configurable (default 5), never corpus-wide.
4. **Relevance gate.** If the best retrieved chunk's similarity score is below a configured
   threshold, the endpoint returns a graceful decline (a real, honest "that doesn't look related
   to this lesson" message) **without calling `LLM_TUTOR` at all** — no cost, no hallucinated
   answer from the model's general knowledge (matches this product's existing no-clinical-claims,
   no-invented-fact discipline).
5. Otherwise, `LLM_TUTOR` (via `get_llm_provider(settings.llm_tutor).complete(...)`, never a
   direct provider import in `service.py`) is called with the retrieved chunks + question +
   segment context, `max_tokens` capped, and the real answer text is returned to the caller.
6. One `session_events` row is written per question (`event_type: "tutor_question"`), whether
   answered or declined, carrying `{segment_id, question_text, audio_position_ms, answer,
   declined, retrieved_chunk_ids, model, cost_usd}` — extends D149's originally-proposed contract
   (chunk IDs, model, cost added) rather than replacing it.
7. `## Scale & Load` section (this file) answers all six `docs/SCALE-CONTRACT.md` questions.

## Scale & Load

1. **What is ONE unit of work, and what is its range?**
   One unit is one tutor question: one embedding call (1 text, ~tens of tokens) + one pgvector
   top-K search (K=5 default) + at most one `LLM_TUTOR` completion (question + up to 5 chunks +
   segment context as input, `max_tokens`-capped output). Range: 0 questions/session (never
   asked) up to the per-session cap this story adds (Task 3) — unlike lesson generation, there is
   no "largest actually measured" yet, because nothing has ever been askable; this section's
   answer is analytic (derived from the code and the cap being added), not measured, and is the
   first real measurement opportunity once this ships.

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   - **Question count per session** — fixed cap (Task 3, Redis-enforced), configurable via
     `settings.tutor_qa_max_questions_per_session` (default reasoned, not yet calibrated against
     real usage — flagged as a candidate for real-data tuning once sessions exist). Past it:
     explicit decline message, AC2 — never silent, never unbounded.
   - **Top-K retrieved chunks** — fixed at `settings.tutor_qa_top_k` (default 5). A chapter with
     fewer than K chunks simply returns fewer — no truncation risk, pgvector's `LIMIT` clause
     degrades gracefully to "all available" below K.
   - **`max_tokens` on the `LLM_TUTOR` completion** — fixed, bounds worst-case per-question cost
     directly (this is the mechanism replacing a dedicated cost-ceiling subsystem — see "out of
     scope" above). Past it: the completion is truncated by the provider itself (OpenAI's own
     `finish_reason: "length"` behavior) — **flagged, not silently accepted**: AC5's response
     includes `finish_reason` in the logged `session_events` payload so a truncated real answer is
     visible on the record, not indistinguishable from a complete one. This is the one place this
     story's own budget could itself become a silent-truncation risk if unflagged — closed by
     logging it, not by assuming `max_tokens` is generous enough to never bind.
   - **Relevance threshold (AC4)** — fixed cutoff. A borderline-relevant question near the
     threshold either declines (false negative, costs the student a wasted "not related" message)
     or answers thinly (false positive) — both explicit, neither silent; not tunable against real
     data yet, same caveat as the question-count cap.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   Per session (the question-count cap), keyed by `session_id` in Redis — correctly scoped
   regardless of replica count, unlike D49's original per-process rate limiter, because this uses
   the app-level `redis.incr`/`redis.expire` pattern (`core/redis.py`'s shared pool) already
   proven correct for `segment_index`, not `slowapi`'s process-local storage. Retrieval scope
   (Q3 in the AC sense, not this Scale question) is per-lesson (`chapter_id`/`book_id`), stated
   explicitly in AC3 — never corpus-wide across all books.

4. **Which reads and writes are UNBOUNDED?**
   None, with reason. The pgvector search carries an explicit `LIMIT` (top-K). The session
   ownership check is a single-row lookup by primary key. The `session_events` insert is one row
   per question, bounded by the question-count cap itself (Q2) — a session can never accumulate
   more `tutor_question` events than its own cap allows, so this read/write path is
   self-bounding, not merely "not yet observed to be large."

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   N/A — every cap this story introduces (question count, top-K, `max_tokens`, relevance
   threshold) is new, sized by reasoning stated inline (Q2), not inherited from an unrelated
   prior unit of work. Nothing here repeats the 50 MB-cap class of mistake.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   The one real check-then-act in this story: reading the current question count, comparing to
   the cap, then incrementing. **Made safe by using `redis.incr` as the act itself, not a
   separate write after a separate read** — `INCR` returns the post-increment value atomically,
   so the cap comparison happens on the atomically-incremented number, not on a stale read from
   before a concurrent request's own increment. Two simultaneous requests at the boundary both
   increment, and each sees its own true post-increment count — the one that pushes the counter
   over the cap is the one that gets the decline, deterministically, not a race where both could
   slip through (the shape `generate_chapter_lesson`'s **D45** explicitly does NOT have — this
   story's mechanism is deliberately the safe pattern, not a repeat of that gap).

## Tasks / Subtasks

- [ ] **Task 1 — Schemas + router (AC: #1, #6)**
  - [ ] `TutorQuestionSubmission` / `TutorQuestionResult` in `assessment/schemas.py`, matching
    the frontend's `SubmitTutorQuestionPayload`/`SubmitTutorQuestionResult` field names exactly
    (`session_id, segment_id, question_text, audio_position_ms` in; `received, answer, declined`
    out) so the eventual frontend swap needs zero payload-shape translation.
  - [ ] `POST /assessment/session/{session_id}/questions` in `router.py`, mirroring
    `submit_quiz`'s auth/DI pattern (`CurrentUser`, lazy `get_supabase()` import).
  - [ ] Session-ownership check (403/404), mirroring `grade_quiz`'s existing pattern exactly —
    no new IDOR-guard shape invented.

- [ ] **Task 2 — Retrieval (AC: #3)**
  - [ ] `answer_tutor_question(...)` in `service.py`: resolve `session.lesson_id` →
    `lessons.chapter_id` (fallback `lessons.book_id` if null) via a single-row lookup.
  - [ ] Embed the question: `OpenAIEmbeddingsProvider().embed_texts([question_text])` — one
    provider call, query-time embedding, explicitly permitted per CLAUDE.md.
  - [ ] pgvector cosine-similarity top-K query against `chunks`, filtered by the resolved
    `chapter_id`/`book_id`, `LIMIT settings.tutor_qa_top_k`.

- [ ] **Task 3 — Rate limit + relevance gate (AC: #2, #4)**
  - [ ] `session:{session_id}:tutor_question_count` — `redis.incr` + `redis.expire` (session
    lifetime TTL, matching `segment_index`'s existing pattern) — compare the atomically-returned
    post-increment value against `settings.tutor_qa_max_questions_per_session`.
  - [ ] Over cap: explicit decline response, no embedding/LLM call, `session_events` row still
    written (`declined: true`, `answer: null`) so the attempt is on the record.
  - [ ] Relevance gate: best retrieved chunk's similarity score vs.
    `settings.tutor_qa_relevance_threshold` — below threshold, decline gracefully, no LLM call.

- [ ] **Task 4 — LLM_TUTOR call + logging (AC: #5, #6)**
  - [ ] `get_llm_provider(settings.llm_tutor).complete(messages, model=settings.llm_tutor,
    max_tokens=settings.tutor_qa_max_answer_tokens)` — never a direct `OpenAILLMProvider` import
    in `service.py` (CLAUDE.md's provider-abstraction rule).
  - [ ] Prompt: retrieved chunks + question + segment context — grounded, not the model's general
    knowledge (matches AC4's intent even on the answered path, not just the declined one).
  - [ ] `session_events` insert: `{segment_id, question_text, audio_position_ms, answer, declined,
    retrieved_chunk_ids, model, cost_usd, finish_reason}`.

- [ ] **Task 5 — Tests**
  - [ ] Session ownership: 403 on a foreign session, 404 on a missing one (mirrors `grade_quiz`'s
    existing tests).
  - [ ] Rate limit: cap reached → decline, no provider calls made (mocked, asserted not-called);
    concurrent-increment race test proving two simultaneous requests at the boundary each see
    their own true count (Scale & Load Q6).
  - [ ] Relevance gate: below-threshold retrieval → decline, no `LLM_TUTOR` call made.
  - [ ] Happy path: real retrieval + real `LLM_TUTOR` call (mocked provider) → answer returned,
    `session_events` row shape asserted field-by-field.
  - [ ] `finish_reason: "length"` (truncated answer) is logged, not silently treated as complete.

- [ ] **Task 6 — Config + register/tracker close-out**
  - [ ] New `Settings` fields: `tutor_qa_max_questions_per_session`, `tutor_qa_top_k`,
    `tutor_qa_relevance_threshold`, `tutor_qa_max_answer_tokens` — all with reasoned (not
    measured) defaults, stated as such in each field's description.
  - [ ] `docs/DEFECT-REGISTER.md`: update D149's disposition from "registered, not fixed" to
    closed/superseded by this story, or open a fresh entry if D149's exact wording doesn't fit a
    clean close — decide during implementation, not pre-committed here.
  - [ ] `docs/dev4-tracker.md`: this story doesn't fit the existing Sprint/BR sections cleanly
    (it's Phase 2, cross-module) — add a new "Phase 2" section rather than forcing it into an
    ill-fitting existing one, matching this file's own established pattern of adding sections
    rather than overloading old ones.

## Dev Notes

- **Module boundary.** The real endpoint lives in `assessment/` (matching D149's own proposed
  ownership and this router's existing quiz/teachback/session convention), not `tutor/`. This
  story's only `tutor/` involvement is the FSM investigation already resolved above (no code
  change needed there) — respecting CLAUDE.md's "one discipline rule" (modules communicate only
  through the service layer) rather than reaching into `tutor/`'s Redis keys from `assessment/`
  service code.
- **Why REST, restated plainly:** this is a considered trade against my own earlier stated
  preference (WS), made explicit here rather than silently reversed — see "out of scope" above.
- **Cost:** unlike lesson generation, this story deliberately does NOT hook into
  `core/cost_tracker.py`'s `$3.00/lesson` ceiling — that ceiling's unit of work is one lesson
  generation, not one live question, and conflating the two would either falsely block Q&A once a
  lesson's generation cost is already accounted for, or silently let Q&A spend ride on a budget
  meant for something else. A dedicated Q&A cost dimension is a real future need (flagged, Scale
  & Load Q2) once real per-question cost data exists — not invented speculatively here.

### Project Structure Notes

- `apps/api/app/modules/assessment/schemas.py` / `router.py` / `service.py` — new
  functions/models, existing files, no new module.
- No `packages/shared` contract change (REST, not WS — see "out of scope").
- No Supabase migration — `chunks.chapter_id`/`book_id`/`embedding` and `session_events` all
  already exist.

### References

- [Source: docs/DEFECT-REGISTER.md#D149] — the gap this story closes.
- [Source: apps/web/src/lib/assessment.ts] — `submitTutorQuestion()`'s exact current stub
  contract, matched field-for-field by this story's schemas.
- [Source: apps/web/src/components/player/AskTutorPanel.tsx] — the real, shipped call site.
- [Source: apps/api/app/config.py:349-354] — `llm_tutor` field, already reserved, unused until
  this story.
- [Source: apps/api/app/providers/base.py] — `LLMProvider.complete()`, `EmbeddingsProvider.
  embed_texts()`; the "Phase 2 RAG tutor query-embedding IS allowed" docstring note.
- [Source: apps/api/app/providers/llm/factory.py] — `get_llm_provider()`, the required call path.
- [Source: apps/api/app/providers/embeddings/openai.py] — the real embedding provider this story
  reuses unmodified.
- [Source: apps/api/app/modules/assessment/service.py:342-380] — `grade_quiz`'s ownership-check
  and DI pattern, mirrored by this story's new endpoint.
- [Source: apps/api/app/modules/tutor/service.py:607-634] — the fatigue-trigger block proving no
  FSM change is needed (only executes inside an `attention_signal` handler, no background timer).
- [Source: supabase/migrations/20260625000000_chunks_inline_embedding.sql] — `chunks.book_id`,
  `chunks.embedding vector(1536)`, HNSW index.
- [Source: supabase/migrations/20260803000000_chapters_book_scoped.sql] — `lessons.chapter_id`.
- [Source: supabase/migrations/20260611000000_initial_schema.sql] — `session_events` schema.
- [Source: CLAUDE.md#Tutor-State-Machine, #Development-Rules] — "no GPT call at intervention
  time" (this story's deliberate exception), provider-abstraction rule, one-discipline rule.
- [Source: docs/SCALE-CONTRACT.md] — the six questions answered above.
