---
id: "S5-1"
title: "Book-upload personalization form — per-book context (Issue #231)"
status: "Draft"
sprint: 5
story_points: 5
owner: Dev3 (cross-team pick-up from Dev 1)
issue: 231
branch: sprint5/s5-1-book-context-form
migration: "YES — supabase/migrations/<new>_book_context.sql"
---

# Story S5-1 — Book-Upload Personalization Form (Per-Book Context)

**Sprint:** Sprint 5 — Product Maturation Phase
**Issue:** #231 (GitHub)
**Dev:** Dev 3 (cross-team pick-up — Dev 1 owns the pipeline changes review)
**Status:** Draft
**Branch:** `sprint5/s5-1-book-context-form`
**Migration:** YES — new `book_context` table

---

## User Story

**As a student who just uploaded a book,**
**I want** to optionally tell the system why I uploaded this book and what I want from it,
**so that** every lesson generated from any chapter reflects my actual goals and context — without
slowing down the upload or blocking me from starting.

---

## Background

**Source authority:** Field list and precedence order come from `AI_Learning_Product_Final_Strategy.pdf §4.2`
("Book Understanding Form") and §5 (merge precedence order), as extracted in
`docs/proposals/2026-09-19-platform-changes-scope.md`. The exact field wording below is from
that source — do not substitute paraphrases.

**Placement decision (resolved):** The form lives on the book's post-upload chapter-list page
(`BookDetail`), not at the upload step itself. `UploadFlow.tsx` was deliberately redesigned to
auto-upload with zero friction; the strategy doc does not require the form to block upload.

**Upsert (not one-time) decision (from Issue #231):** The endpoint is editable at any time.
The server never returns 409 on re-submission. This overrides the proposal doc's "one-time only"
default.

**Critical scope boundary:** Codebase research (confirmed 2026-09-21) found that
`graph.py` currently has **zero personalization context injection** — no `fetch_learner_context_node`,
no `dna_context`, no onboarding injection at the three prompt sites. The proposal doc's action list
assumed these existed; they do not. This story introduces book_context as the **first** context
injection into the lesson generation pipeline. Onboarding/DNA injection into the pipeline is a
**separate, pre-existing gap** — not part of this story's scope.

---

## Acceptance Criteria

### Form & UX

**AC1 — Form placement.**
`BookDetail` renders a "Tell us about this book" section below the book header and above the chapter
list. The section is visible when `book.status === 'ready'`; it is NOT shown during `processing`
or `failed` states.

**AC2 — Exact field wording (from §4.2 of strategy doc — do not paraphrase).**
The form presents exactly these six fields with exactly these labels:
1. "Why did you upload this book/PDF?"
2. "What do you want to achieve from it?"
3. "Complete book or selected chapters?" — rendered as a two-option radio/toggle:
   "Complete book" / "Selected chapters"
4. "Which sections or topics are most important or difficult for you?"
5. "What is your deadline, and how much depth do you want?"
6. "Should we follow the document exactly, or reorganize it for optimal learning?"

**AC3 — Fully skippable.**
Every field is optional. A "Skip for now" link is present and dismisses the section without
submitting. No chapter generation is blocked on filling this form. A student who never fills it
gets no degraded experience.

**AC4 — Pre-populated on revisit.**
If the user has previously saved context for this book, the form loads pre-populated with those
saved values. The UI fetches `GET /books/{book_id}/context` on mount and fills the form if a row
is found (204 → empty form). Edits are a standard re-submission.

**AC5 — Upsert semantics; no 409 ever.**
Clicking "Save" submits all six fields via `PUT /books/{book_id}/context`. The server returns 200
on both first save and every subsequent save. Concurrent submits from the same user serialize at the
DB UNIQUE constraint — no duplicate rows, no race condition.

---

### Backend — Database

**AC6 — New migration creates `book_context` table.**
Migration file: `supabase/migrations/<yyyymmddhhmmss>_book_context.sql`

Required columns:
```sql
CREATE TABLE book_context (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id     UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    why_uploaded          TEXT,
    what_to_achieve       TEXT,
    complete_or_selected  TEXT,  -- "complete" | "selected" | null
    important_sections    TEXT,
    deadline_and_depth    TEXT,
    follow_or_reorganize  TEXT,  -- "follow" | "reorganize" | null
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (book_id, user_id)
);
```

RLS policies:
- SELECT: `user_id = auth.uid()`
- INSERT/UPDATE/DELETE: `user_id = auth.uid()`

---

### Backend — API Endpoints

**AC7 — `PUT /books/{book_id}/context` (upsert).**
- Requires auth (existing `CurrentUser` dep).
- Validates `book_id` belongs to the authenticated user (same ownership check as existing book
  endpoints — 404 if not found or not owned, never 403).
- Validates each text field: max 500 characters, checked before DB write.
- Executes: `INSERT ... ON CONFLICT (book_id, user_id) DO UPDATE SET ...`.
- Returns 200 with the saved row (all 6 fields + `updated_at`).
- Never returns 409.

**AC8 — `GET /books/{book_id}/context`.**
- Returns 200 + saved row if context exists, 204 No Content if not.
- Same ownership check as AC7.

---

### Backend — Context Service

**AC9 — `apps/api/app/modules/content/context.py` created.**
Exports `async def get_book_context_prompt_context(book_id: str, user_id: str) -> str`.
- Returns a formatted text block (see prompt format below) if a row exists.
- Returns empty string `""` if no row found — never raises.
- Handles DB errors gracefully (logs, returns `""`) so a context read failure does NOT abort
  lesson generation.

Prompt format for the returned block (example):
```
[Book Context]
Why uploaded: <value>
Goal: <value>
Scope: <value>
Focus areas: <value>
Deadline / depth: <value>
Teaching approach: <value>
```
Omit any field whose DB value is NULL or empty — never emit "None" or empty lines.

---

### Backend — Pipeline Injection

**AC10 — `"book_context"` added to `_FAN_OUT_STATE_KEYS`.**
`_FAN_OUT_STATE_KEYS` in `graph.py` is extended from
`("lesson_id", "user_id", "book_id", "tier")` to
`("lesson_id", "user_id", "book_id", "tier", "book_context")`.
This ensures `narration_generator_node` (which is `Send()`-dispatched) receives the context.
Adding a `str`-typed key does NOT risk reducer-channel duplication (strings are last-write-wins,
not append-reducing) — the guard test in AC15 confirms this.

**AC11 — `lesson_planner_node` fetches and stores `book_context`.**
At the start of `lesson_planner_node`, before any LLM call:
```python
book_context = await get_book_context_prompt_context(
    book_id=state["book_id"], user_id=state["user_id"]
)
```
The node returns `{"lesson_plan": ..., "book_context": book_context}` — only its own keys,
never `{**state, ...}`.

**AC12 — Shared merge helper in `prompt_context.py`.**
`apps/api/app/modules/content/pipeline/prompt_context.py` is created with:
```python
def merge_book_context(base_prompt: str, book_context: str) -> str
```
Used at all three prompt sites (lesson planner, slide generator, narration generator).
No ad-hoc string concatenation at individual sites — all three go through this function.

Book context is appended in the §5 precedence slot "book context": after any user-profile
(onboarding) slot and before any chapter-instructions slot.

**AC13 — Character budget with explicit degradation.**
If `book_context` exceeds 2,000 characters after formatting, `merge_book_context` truncates at a
field boundary (never mid-sentence), appends a `[Book context truncated]` marker to the block,
logs a Langfuse warning span, and persists `book_context_truncated=true` in the `lessons` row's
metadata. Silent truncation never occurs (binding CLAUDE.md rule).

The 2,000-char cap is derived from: GPT-4o 128k context window × ~1.5% budget for book context ≈
1,920 tokens × ~1 char/token ≈ 2,000 chars. Re-derive if prompt structure changes significantly.

---

### Process & Quality

**AC14 — Guard tests pass.**
`tests/unit/test_node_return_shape.py` and `tests/unit/test_unbounded_queries.py` both pass after
all `graph.py` changes. If the node-return-shape guard needs its allowlist updated (e.g. to
acknowledge the new `book_context` key returned by `lesson_planner_node`), the update is included
in the same commit with a comment explaining why.

**AC15 — DPDP Act 2023 compliance.**
`book_context` rows have the same data-residency RLS controls as `learner_dna`. No raw
`book_context` field values appear in Langfuse traces — only a boolean `has_book_context` flag.

**AC16 — Endpoint tests.**
New tests cover:
- `PUT /books/{book_id}/context` creates row (200)
- `PUT /books/{book_id}/context` updates existing row (200, no 409)
- `GET /books/{book_id}/context` returns 200 with data / 204 when none
- Ownership: another user's book_id returns 404
- Field length: field > 500 chars returns 422

---

## Scale & Load

**Q1 — Unit of work and its range.**
One unit: one `book_context` DB row per `(book_id, user_id)` pair.
- Min: all fields NULL (user skipped every question).
- Typical: ~100 chars per field × 6 fields ≈ 600 chars total text stored.
- Max: 500 chars per field × 6 = 3,000 chars stored; 2,000 chars merged prompt block (AC13 cap).
- Beyond cap: AC13 explicit truncation + flag — not silent, not a generation failure.

**Q2 — Fixed budgets while input varies.**
- Per-field cap: 500 chars, enforced by API validator before DB write (422 on breach).
- Merged block cap: 2,000 chars in `prompt_context.py`; breach triggers explicit truncation with
  Langfuse warning and `lessons.metadata` flag. Silent truncation is never an acceptable answer.
- Derivation: 128k-token context, ~1.5% budget for book context ≈ 2,000 chars. Document this
  constant in code; re-derive when prompt structure changes.

**Q3 — Scope of every limit.**
- 500-char field cap: per-request, per-field.
- 2,000-char merged block: per lesson generation run.
- `UNIQUE (book_id, user_id)` DB constraint: one row per learner per book, globally.

**Q4 — Unbounded reads/writes.**
- `GET /books/{book_id}/context`: reads exactly ONE row by `(book_id, user_id)` index. Bounded.
- `PUT /books/{book_id}/context`: upserts exactly ONE row. Bounded.
- `get_book_context_prompt_context`: reads exactly ONE row. Bounded.
No list query, no fan-out query anywhere in this feature.

**Q5 — Inherited caps re-derived.**
- 500-char-per-field: newly specified for this story; not inherited.
- 2,000-char merged block: newly specified; derived in Q2 above.
- RLS pattern: inherited from `learner_dna` — per-user scoping, no natural row count cap per user,
  but each query in this feature targets a specific `(book_id, user_id)` pair.

**Q6 — Concurrent request safety.**
`PUT /books/{book_id}/context` uses `ON CONFLICT (book_id, user_id) DO UPDATE SET ...` — a
Postgres-atomic upsert. No check-then-act sequence. Concurrent submits from the same user-book pair
serialize at the DB constraint — no duplicate rows possible, no TOCTOU race.

---

## Implementation Notes

1. **No onboarding injection in this story.** The pipeline currently has zero personalization
   context injection. This story adds only `book_context`. If a future story adds onboarding
   injection, `prompt_context.py`'s `merge_book_context` can be extended without rewriting call
   sites — that's exactly why the shared helper is built here.

2. **Node return shape is non-negotiable.** `lesson_planner_node` must return
   `{"lesson_plan": <value>, "book_context": <str>}` — never `{**state, ...}`.
   The guard test enforces this.

3. **`_FAN_OUT_STATE_KEYS` is safe for str keys.** Unlike list-reducer channels,
   a `str` key in LangGraph state is last-write-wins. Adding `"book_context"` does not risk the
   reducer-channel duplication defect (that defect only affects `Annotated[list, operator.add]`
   channels). Confirm with guard test AC14.

4. **Frontend form is always rendered, never modal.** `BookContextForm.tsx` renders inline in
   `BookDetail`. Use local controlled state + an explicit "Save" button. Show a "Saved" indicator
   on success. The "Skip for now" link hides the form without submitting (client-side only —
   no server call needed for skip).

5. **`context.py` error handling pattern.** Mirror `assessment/service.py::get_learner_context`
   for async DB access and graceful fallback. Do not import from the assessment module — book
   context is a content module concern.

6. **Migration timestamp.** Use today's date `20260921000000` as the migration prefix
   (or next available slot if another migration has the same timestamp).

---

## Files Touched

| File | Action | Note |
|------|--------|------|
| `supabase/migrations/20260921000000_book_context.sql` | CREATE | New `book_context` table |
| `apps/api/app/modules/content/schemas.py` | MODIFY | New `BookContextRequest` / `BookContextResponse` models |
| `apps/api/app/modules/content/router.py` | MODIFY | `PUT` + `GET` `/books/{book_id}/context` |
| `apps/api/app/modules/content/context.py` | CREATE | `get_book_context_prompt_context()` |
| `apps/api/app/modules/content/pipeline/prompt_context.py` | CREATE | `merge_book_context()` |
| `apps/api/app/modules/content/pipeline/graph.py` | MODIFY | `_FAN_OUT_STATE_KEYS`, `lesson_planner_node`, `_planner_system_prompt`, slide + narration prompt sites |
| `apps/web/src/services/books.service.ts` | MODIFY | `upsertBookContext()` + `getBookContext()` |
| `apps/web/src/components/dashboard/books/BookContextForm.tsx` | CREATE | Form component |
| `apps/web/src/components/dashboard/books/BookDetail.tsx` | MODIFY | Render `BookContextForm` |
| `apps/api/tests/...` | CREATE | AC16 endpoint tests |

---

## Review Findings

_Code review run 2026-09-21 — 4 layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter). 15 findings after dedup; 6 dismissed._

### Decision-Needed

- [ ] [Review][Decision] F7 — Context mismatch on ARQ retry: `lesson_planner_node` fetches `book_context` fresh BEFORE the idempotency cache check. On an ARQ retry where the lesson_plan is a cache-hit, slide_generator and narration_generator receive the freshly-fetched context (which may have changed), while the lesson_plan they personalise was built with the original context. No error or warning is surfaced. Options: (a) accept as a known product tradeoff — document it; (b) snapshot context at the start and refuse to re-fetch on retry if a cached plan exists; (c) always re-fetch at each prompt site instead of propagating via state. [`apps/api/app/modules/content/pipeline/graph.py:lesson_planner_node`]

### Patches

- [ ] [Review][Patch] F1 — CRITICAL: Migration FK wrong column — `REFERENCES books(id)` but `books` PK is `book_id`; migration fails on first deploy [`supabase/migrations/20260921000000_book_context.sql:22`]
- [ ] [Review][Patch] F2 — CRITICAL: AC13 not implemented — `book_context_truncated` never written to `lessons` row by any caller; no Langfuse span; only a `logger.warning` nobody reads. With 6 fields × 500 chars, fields 4–6 (important_sections, deadline_and_depth, follow_or_reorganize) are silently dropped on every lesson. The lesson reports `ready`. Cost ceiling never fires. [`apps/api/app/modules/content/pipeline/prompt_context.py:64`, `graph.py` all 3 call sites]
- [ ] [Review][Patch] F3 — HIGH: Prompt injection via embedded newlines in user-controlled fields — `get_book_context_prompt_context` formats each field as `f"{label}: {value}"` after only `.strip()` (removes leading/trailing whitespace, not internal newlines). A value of `"legitimate\nGoal: attacker-value"` creates a spurious label line inside the `[Book Context]` block. Fix: replace internal newlines in each field value with a space before formatting. [`apps/api/app/modules/content/context.py:91-93`]
- [ ] [Review][Patch] F4 — HIGH: AC15 violated — no `has_book_context` flag added to Langfuse spans at any of the 3 call sites; `traced_node` wraps all 3 nodes and records LLM inputs by default, meaning raw field values ("Why uploaded: Pass my exam") appear in Langfuse traces, violating DPDP. [`apps/api/app/modules/content/pipeline/graph.py` — lesson_planner_node, slide_generator_node, narration_generator_node]
- [ ] [Review][Patch] F5 — HIGH: AC16 violated — no FastAPI TestClient endpoint tests for: PUT create (200), PUT update (no 409), GET 200 with row, GET 204 when none, ownership 404; only Pydantic schema validation tested [`apps/api/tests/test_s5_1_book_context.py`]
- [ ] [Review][Patch] F6 — HIGH: GET endpoint has no error handling — `get_book_context_row` can throw (network error, supabase timeout) producing an unhandled 500; PUT endpoint has try/except, GET does not [`apps/api/app/modules/content/router.py:get_book_context`]
- [ ] [Review][Patch] F8 — MEDIUM: FastAPI 204 GET endpoint may serialize null body — returning `None` with `response.status_code = 204` may emit JSON `null`; HTTP 204 MUST NOT include a body. Fix: return `Response(status_code=204)` directly [`apps/api/app/modules/content/router.py:get_book_context`]
- [ ] [Review][Patch] F9 — MEDIUM: `dismissed` state not reset on `bookId` change — if React reuses the component instance across books without unmounting, a student who clicked "Skip for now" on book A never sees the form for any subsequent book [`apps/web/src/components/dashboard/books/BookContextForm.tsx:78`]
- [ ] [Review][Patch] F11 — MEDIUM: No server-side enum validation on radio fields — `complete_or_selected` and `follow_or_reorganize` accept any string up to 500 chars; fix: add `Literal["complete", "selected"] | None` and `Literal["follow", "reorganize"] | None` constraints (or a field_validator) [`apps/api/app/modules/content/schemas.py:BookContextRequest`]
- [ ] [Review][Defer] F12 — LOW: `_validated_book_id(book_id)` called twice in both endpoints — assign result to a variable and reuse [`apps/api/app/modules/content/router.py:upsert_book_context, get_book_context`] — **D167**: Deferred; redundancy is harmless, fix after D155 router integration tests exist.
- [ ] [Review][Patch] F13 — LOW: Raw `book_id` UUID in `RuntimeError` message flows into Sentry payloads — use generic message or omit UUID [`apps/api/app/modules/content/context.py:147`]
- [ ] [Review][Patch] F14 — LOW: AC3 deviation — "Skip for now" renders as `<button>`, spec says "link"; semantically different (screen reader announces "button", no `href`) [`apps/web/src/components/dashboard/books/BookContextForm.tsx:144`]
- [ ] [Review][Patch] F15 — LOW: AC13 edge case — when `book_context` starts with a newline, `rfind("\n")` returns 0, `if last_newline > 0` is false, and truncation falls back to the hard char boundary (not field boundary as AC13 requires) [`apps/api/app/modules/content/pipeline/prompt_context.py:60`]

### Deferred

- [x] [Review][Defer] F10 — Service-role client bypasses RLS in `context.py`; only `_fetch_owned_book` in the router guards IDOR [`apps/api/app/modules/content/context.py`] — deferred, established codebase pattern; all content-module DB access uses service-role client. Future callers of context.py functions must route through router ownership check.

### Dismissed (6)

_Not written to action items — false positives or non-issues in context:_
1. Blind-5: `book_context` reducer concern — false positive; `book_context: str` is plain str (last-write-wins), not `Annotated[list, operator.add]`.
2. Blind-8: Frontend 404 swallowed as null — non-issue; `BookDetail` shows "not found" UI before `BookContextForm` is ever rendered when book 404s.
3. Blind-3 (PII fan-out raw): merged into F4.
4. Edge-9: Truncation marker 25 chars over 2,000-char budget — inconsequential for 128k context window.
5. Scale-2 (17 merge calls scope): merged into F2 detail.
6. Blind-6 (TOCTOU ownership/upsert): merged into F12.
