# Deferred Work

Items deferred from code review — not urgent for current sprint but should be tracked.

---

## Deferred from: code review of 2-5-player-state-persistence (2026-07-06)

- **`quizFiredForSegment` restore is validated only by index-bounds, not segment-ID identity** [`apps/web/src/stores/player.machine.ts`] — if the same `lesson_id` is later regenerated with different segment content that still satisfies the bounds check against the new `segments.length`, previously-fired quiz IDs could be restored and suppress quizzes the student never actually completed in the new content. Would need content-identity validation (e.g. hashing segment IDs) beyond this story's scope.
- **Saved progress has no user/account scoping** [`apps/web/src/stores/player.machine.ts`] — keyed only by `lesson_id`; on a shared/public device, a second student opening the same lesson after the first left mid-session would silently inherit the first student's segment/position/quiz-fired state. `player.machine.ts` doesn't track `user_id` anywhere today — needs a product/architecture decision, not a one-line patch.
- **No `storage` event listener for multi-tab conflicts** [`apps/web/src/stores/player.machine.ts`] — two tabs with the same lesson open independently write to the same `hie:session:{lesson_id}` key with no conflict detection; whichever tab saves last silently wins, potentially clobbering further-along progress from the other tab. A real fix needs a `storage` event listener plus conflict-resolution UX.
- **`Player.tsx`'s mount effect re-runs on any `lesson` prop reference change, not just a genuine lesson change** [`apps/web/src/components/player/Player.tsx`] — re-surfaced during this story's review (originally flagged in Story 2-4's review): React StrictMode's dev-only double-invoke, or a future non-memoized lesson source, would re-run both `loadLesson` and (as of this story) `restoreProgress` unnecessarily. Pre-existing `loadLesson` mount-effect design, not introduced by this story.

## Deferred from: code review of 2-4-session-report-page (2026-07-04)

- **`Player.tsx`'s mount effect unconditionally calls `loadLesson(lesson)`, resetting `status` to `IDLE`** [`apps/web/src/components/player/Player.tsx`] — any remount with a new `lesson` object reference (not just the initial mount) silently reverts an `ENDED` state and its session-report link. Pre-existing effect design, not introduced by this story; the new `Player.test.tsx` documents and works around it (sets `status: 'ENDED'` after `render()`, not before) rather than fixing the underlying effect, which needs broader consideration than a UI story's scope.
- **`ces_score: 0.0` is ambiguous between "never calculated" and "genuinely fully disengaged"** [`apps/web/src/lib/utils.ts:formatCesLabel`] — the backend returns `0.0` for both `ces_final IS NULL` and an authentically low-CES session (story 3-19 AC 4, already adversarially reviewed and merged), with no distinguishing field in the response. Not fixable frontend-only; would need a Dev 3 contract change.
- **A student can view `/reports/{sessionId}` for a session whose `ended_at` is still `NULL`** [`apps/web/src/components/reports/SessionReport.tsx`] — shows an internally inconsistent report (zero duration/no timestamp alongside possibly non-zero quiz/intervention data). Low real-world likelihood given the only in-app entry point is the post-`ENDED` player link; acceptable for v1. Consider a "session still in progress" state if this proves to matter in practice.

## Deferred from: code review of 2-3-onboarding-assessment-flow (2026-07-04)

- **DPDP `user_consents` gap for `consent_type='learner_dna'`** [`supabase/migrations/20260702000000_dpdp_user_consents.sql`] — the schema already supports a `learner_dna` consent record (added in Story 3-17 alongside `attention_tracking`), but nothing anywhere — frontend or `process_onboarding()` backend service — ever writes that row. Same class of gap CLAUDE.md §18 already flagged and fixed for `attention_tracking`. Needs a deliberate decision with Dev 3/Dev 1 (policy_version, insertion point), not a frontend-only fix.
- **No runtime API-response schema validation or error boundary anywhere in the onboarding route tree** [`apps/web/src/components/onboarding/DNAResultCard.tsx`] — `badge_labels`/`profile_text` are trusted via TS types only (`api.get<T>()`/`api.post<T>()` casts), with no runtime guard and no error boundary anywhere in the app to catch a shape-drift crash. Pre-existing project-wide practice gap, broader than this story.
- **Middleware does a live, uncached Supabase round-trip on every `/lesson/**`/`/upload/**` request** [`apps/web/src/middleware.ts`] — adds a DB hit + latency to the hottest part of the app on every navigation. Acceptable for Sprint 2 MVP scope; a real fix needs either a client-writable cookie (a security regression on a security-relevant gate) or a backend JWT-claim change (out of scope for a frontend story).
- **`OnboardingFlow`'s mount-time `getLearnerDna()` call has no timeout** [`apps/web/src/components/onboarding/OnboardingFlow.tsx`] — a hung request strands the user on an infinite spinner. Root cause is project-wide: `lib/api.ts`'s shared axios instance has no default `timeout` configured at all. Fixing it properly means adding a default timeout project-wide (out of this story's file list) rather than a one-off local fix.

## Deferred from: code review of 1-15-brand-recolor (2026-07-02)

- **`/onboarding/page.tsx` is unbranded and has dead/no-op button classes** [`apps/web/src/app/onboarding/page.tsx`] — pre-existing, not touched by the S1-15 diff: it's the only route in the app using `dark:` Tailwind variants (will flip to a dark theme under OS dark mode while every other page stays light); uses `bg-primary-600`/`text-primary-700`-style numbered-scale classes that don't resolve to anything (no `tailwind.config`, no `--color-primary-600` token defined), so several buttons/selected-states on this live, auth-gated route likely render without their intended background; also still shows leftover copy "TransformED AI" instead of "HIE". Needs its own follow-up story.
- **Bare untokenized hex `#E8D08D` (lighter gold tint)** [`apps/web/src/components/ui/AuroraBackground.tsx`, `apps/web/src/components/sections/JourneyToSelfReliance.tsx`] — introduced as a literal rather than a named CSS variable; low priority, but a future gold retune would miss this shade on a `--accent-secondary` grep.
- **AC9 visual verification incomplete** [`_bmad-output/implementation-artifacts/1-15-brand-recolor.md`] — dashboard sidebar/nav active states, `QuizOverlay`, `TeachBackModal`, and `PlayerControls` were named in AC9's required manual-check list but never actually screenshotted; only landing and signup pages were. Recommend a follow-up manual pass with real auth credentials.
- **Residual cool-toned `slate-*` grays** [`apps/web/src/components/sections/CognitiveVisualization.tsx`, `apps/web/src/components/sections/Hero.tsx`, `apps/web/src/components/sections/HowItWorks.tsx`] — several `slate-*` Tailwind classes and matching hex literals remain from the old blue-family palette; not literally "blue" so out of this story's grep-defined scope, but read slightly mismatched against the new warm Navy/Gold/Grey system. Design-consistency nit, not a functional bug.

## Deferred from: code review of 1-07-websocket-client (2026-07-02)

- **`handleClose` gives up silently after 5 reconnect attempts with no way to distinguish "permanently failed" from a transient `closed` state** [`apps/web/src/lib/ws/lessonSocket.ts:handleClose`] — not required by any AC today since nothing consumes `status` yet. Revisit once Sprint 3 wires the lesson player UI to `LessonSocketStatus`.
- **`apps/web/src/lib/assessment.ts` has no tests and doesn't handle a rejected `api.post` call** [`apps/web/src/lib/assessment.ts`] — pre-existing file with unchanged behavior; only newly git-tracked as a side effect of this story's `.gitignore` fix. Out of scope for a WebSocket-client story; needs its own follow-up task.
- **`sendControl()`'s 9 flow events (`segment_complete`, `quiz_trigger`, etc.) have no caller anywhere yet** [`apps/web/src/lib/ws/lessonSocket.ts`] — the receive side (server → store) is wired and tested, but nothing on the player side sends these to drive the backend tutor FSM. Wiring segment-end/quiz-trigger detection to `sendControl()` is separate Sprint 2/3 UI work.

## Deferred from: code review of S0-9 (2026-06-26)

- **`OpenAILLMProvider` captures singleton by reference at construction** [`providers/llm/openai.py:44`] — stale reference in tests if singleton is reset mid-test; not a production bug since singleton is never reset in prod. Revisit if test suite grows to construct providers across singleton resets.
- **`generation.end()` not called on exception path in `openai.py`** [`providers/llm/openai.py:63, 107`] — pre-existing before S0-9; open-ended Langfuse spans on every LLM error obscure error rates. Fix in Sprint 1 when nodes are wired end-to-end.
- **No `atexit` hook for crash-safe flush** [`core/langfuse.py`] — traces lost on SIGKILL or unhandled exception before lifespan shutdown runs. Consider `atexit.register(get_langfuse().flush)` as a safety net in Sprint 2 hardening.
- **Lifespan integration test missing for `flush()` call path** [`tests/unit/test_langfuse_core.py`] — unit tests cover the singleton contract but not the full `main.py` lifespan shutdown sequence. Add in Sprint 1 when test infrastructure for lifespan is established.
- **No concurrency test for singleton race** [`core/langfuse.py`] — race condition (P1) should be fixed first with a `threading.Lock`; add a concurrent-access test after the fix.

---

## Architectural Decision: PyMuPDF Replacement (decided 2026-07-01)

**Context:** `pymupdf` (and `pymupdf4llm`) are AGPL-3.0 — running them as a SaaS web service requires open-sourcing the entire application. Banned per CLAUDE.md.

**Decision:** Replace with the following permissive-licensed stack. No single library replaces all five PyMuPDF capabilities, but the combination below covers them with equal or better quality.

| PyMuPDF capability | Sprint 1 replacement (already installed) | Sprint 2 upgrade (add in Sprint 2) |
|---|---|---|
| Text extraction | `pdfplumber` (MIT) | `pypdfium2` ≥5.11.0,<6.0.0 (Apache 2.0) — 97% acc, 0.003s/page |
| Page rendering for OCR | `pdfplumber` page.to_image() | `pypdfium2` page.render() — bundled engine, no system deps |
| Embedded image extraction | pdfplumber page.images + PIL crop (150 DPI) | `pikepdf` ≥10.0.0,<11.0.0 (MPL 2.0) — lossless, native resolution |
| Layout blocks + font metadata | `pdfplumber` page.chars (fontname, size) | `pdftext` ≥0.6.0,<1.0.0 (Apache 2.0) — structured blocks/lines/spans |
| Table extraction | `pdfplumber` + `docling` (TEDS 0.911 > PyMuPDF 0.692) | No change — docling already wins |

**Sprint 1 action (now):** None. `pdfplumber` + `docling` already covers everything Stories 1.3–1.5 need.
- Story 1.3 rule-based heading detection → use `pdfplumber`'s `page.chars` (each char has `fontname`, `size`, `x0`, `y0`).
- The `HeadingHierarchyOptions` flag in docling (`use_numbering_inference=True`, `use_font_inference=True`) should be enabled in Story 1.3.

**Sprint 2 action:** Before Story 2-1 (Phase 1 economy nodes), add to `pyproject.toml`:
```toml
"pypdfium2>=5.11.0,<6.0.0",
"pdftext>=0.6.0,<1.0.0",
```
Refactor `extract_subprocess.py` to use `pypdfium2` for text and page rendering. When rendering pages for image extraction, use **300 DPI** (not 150) — this closes the quality gap to publisher PDFs without needing pikepdf.

**pikepdf deferred to Sprint 3 conditional:** Add `pikepdf>=10.0.0,<11.0.0` (MPL 2.0) only if pilot data shows ≥30% of uploads are private-publisher PDFs (S Chand, Pearson India) AND students report label legibility failures in science/math diagrams. Migration cost if needed later: ~4 hours (one new extractor function + one re-extraction job). Debated and decided 2026-07-01 via 3-agent parallel debate (2-1 verdict for deferral).

**Permanently banned:** `import fitz`, `pymupdf`, `pymupdf4llm`, `borb` (AGPL-3.0), `marker-pdf` (GPL-3.0), `nougat` (CC-BY-NC weights).

---

## Deferred from: code review of 1-1-post-lessons-endpoint-arq-job-enqueue (2026-06-29)

### W1 — Synchronous Supabase `.execute()` blocks event loop

**File:** `apps/api/app/modules/content/router.py` — all `.execute()` call sites

**Detail:** `supabase-py` v2 `.execute()` is synchronous. Calling it directly in `async def` handlers blocks the event loop for the duration of the network round-trip. Under low concurrency this is acceptable (< 50 ms per call), but under load each blocked handler ties up a worker slot.

**When to fix:** Sprint 4 load-test phase (S4-1). If p95 latency degrades under concurrent uploads, wrap Supabase calls in `asyncio.to_thread()`.

**Resolution path:**
```python
import asyncio
result = await asyncio.to_thread(
    lambda: supabase.table("books").insert({...}).execute()
)
```

---

### W2 — `cost_limit_exceeded` lessons status not in `_STATUS_MAP`

**File:** `apps/api/app/modules/content/router.py:47–51` (`_STATUS_MAP` dict)

**Detail:** The cost-ceiling node (Sprint 2, Story 2-7) will set `lessons.status = "cost_limit_exceeded"` when the $3/lesson cap is breached. This value is not in `_STATUS_MAP`, so `_map_status("cost_limit_exceeded")` silently returns `"queued"` — misleading to the client.

**When to fix:** Story 2-7 (`cost-ceiling-enforcement-all-nodes`). Add entry: `"cost_limit_exceeded": "failed"` (or a dedicated `"cost_exceeded"` client status) when the DB CHECK constraint is defined.

**Resolution path:** Add to `_STATUS_MAP`:
```python
"cost_limit_exceeded": "failed",
```
And expose a distinct client status string if the frontend needs to differentiate cost-exceeded from other failures.

---

## Deferred from: code review of 1-2-pdf-extraction-node-pdfplumber-docling-tesseract-ocr (2026-06-29)

### W1 — `lesson_jobs.status="ready"` violates CHECK constraint

**File:** `apps/api/app/workers/jobs/content_pipeline.py:80–86`

**Detail:** `lesson_jobs.status` CHECK only permits `('pending','running','completed','failed')`. `content_pipeline_job` writes `"ready"` on success — a constraint violation. In supabase-py v2 this raises `APIError`, which the outer except block catches, marks the job as `"failed"`, and re-raises for ARQ retry. Every successful pipeline run is recorded as failed after `max_tries` exhaustion.

**When to fix:** Story 2.7 (`cost-ceiling-enforcement-all-nodes`) — DB CHECK constraint update or rename status to `"completed"`.

---

### W2 — `lessons.status` never updated on success

**File:** `apps/api/app/workers/jobs/content_pipeline.py` (success path)

**Detail:** `content_pipeline_job` only updates `lesson_jobs.status`. `lessons.status` stays at `"generating"` forever. REST polling via `GET /api/content/lessons/{id}` never reflects completion. WebSocket fires `lesson_ready` but polling clients see `"running"` indefinitely.

**When to fix:** Story 2.6 (`package-builder-node`) which handles the `lesson_ready` WebSocket push — add `lessons.status = "ready"` and `completed_at = now()` to the success path at the same time.

---

### W3 — `status="cost_limit_exceeded"` violates CHECK constraint

**File:** `apps/api/app/workers/jobs/content_pipeline.py:116–118`

**Detail:** `_update_lesson_status(supabase, lesson_id, "cost_limit_exceeded", ...)` violates the CHECK constraint. The helper silently swallows the `APIError`, leaving `lesson_jobs.status` stuck at `"running"` permanently.

**When to fix:** Story 2.7 — same CHECK constraint fix as W1 above.

---

### W4 — ~~`_update_job_progress` writes non-existent columns~~ RESOLVED in re-review P1

**File:** `apps/api/app/modules/content/pipeline/graph.py` (`_update_job_progress` helper)

**Detail:** FIXED in re-review pass (2026-06-29). The `progress_pct` (non-existent) and `current_node` (wrong name) columns were removed. `_update_job_progress` now only writes `{"last_node": node_name, "status": "running"}`. If real-time progress percentage is needed in future, add a `progress_pct float` column via migration.

**Remaining gap:** Progress percentage is not tracked in the DB at all (no column). If the frontend needs it, add a migration to `lesson_jobs` and add `"progress_pct": progress_pct` back to the helper update payload.

---

### W5 — `workers/main.py` missing `ssl=` flag for Railway Redis TLS

**File:** `apps/api/app/workers/main.py` `_build_redis_settings()`

**Detail:** `app/main.py` was fixed (Story 1.1) with `ssl=parsed.scheme == "rediss"`. The ARQ worker's equivalent function still lacks the flag, causing the worker process to fail connection on Railway where `REDIS_URL` is `rediss://`.

**When to fix:** Story 1.3 (first story that touches the ARQ worker config).

---

### W6 — Rate limiter `memory://` default bypassed across Railway worker processes

**File:** `apps/api/app/core/rate_limit.py`

**Detail:** `RATE_LIMIT_STORAGE_URL` defaults to `memory://`. Each Railway process has an independent in-memory counter. A user can bypass the `5/minute` upload cap by spreading requests across processes. Fix is an env var deployment concern: set `RATE_LIMIT_STORAGE_URL` to the same Railway Redis URL in production.

**When to fix:** Sprint 4 load-test (`4-2-rate-limiting-stripe-checkout`) — verify env var is set before launch.

---

### W7 — Checkpoint `node_outputs` read-modify-write not atomic

**File:** `apps/api/app/modules/content/pipeline/graph.py` `extract_node`

**Detail:** `node_outputs` is read from `lesson_jobs` at the start of the node, then written back after subprocess work. If two nodes ever write concurrently, one write silently overwrites the other's data. Currently safe because LangGraph executes nodes sequentially. Becomes a bug if the Phase 1 economy nodes are parallelised (planned in Sprint 2).

**When to fix:** Story 2.1 (`phase-1-economy-nodes-all-6-parallel`) — use a DB-level JSONB merge (`|| jsonb_build_object(...)`) instead of read-modify-write.

---

### W8 — ElevenLabs reference in `tts_node` TODO (banned provider)

**File:** `apps/api/app/modules/content/pipeline/graph.py` `tts_node`

**Detail:** A TODO comment references `ElevenLabsTTSProvider`. ElevenLabs is explicitly banned per CLAUDE.md ("ElevenLabs REMOVED"). The correct TTS chain is Sarvam AI Bulbul v2 → Azure TTS → Browser Speech.

**When to fix:** Story 2.4 (`tts-node-sarvam-bulbul-v2-azure-browser-fallback`) — update the TODO and implement the correct provider chain.

---

## Deferred from: re-review of 1-2-pdf-extraction-node (second review pass, 2026-06-29)

### W9 — No tests for docling table path or Tesseract OCR fallback path (AC2 partial)

**File:** `apps/api/tests/unit/test_extract_node.py`

**Detail:** All seven tests exercise the pdfplumber-only happy path. Neither the docling table branch (`has_tables=True` → docling replaces pdfplumber output) nor the Tesseract OCR fallback branch (`avg_chars < threshold and not docling_succeeded`) is covered. Both branches exist in production code with no test coverage.

**When to fix:** Story 1.3 test sprint or first PR touching `extract_subprocess.py`. Add `test_extract_subprocess_docling_tables` and `test_extract_subprocess_ocr_fallback` as integration tests that mock pdfplumber + docling/pytesseract at the module level.

---

### W10 — Silent checkpoint write failure causes idempotency miss on retry (AC4/AC6 coupling)

**File:** `apps/api/app/modules/content/pipeline/graph.py` `extract_node:230-236`

**Detail:** The checkpoint write (`lesson_jobs.node_outputs['extract']`) is wrapped in `except Exception: logger.warning(...)`. A transient DB error returns success to LangGraph but leaves no checkpoint — the next ARQ retry re-runs the subprocess and re-bills downstream LLM nodes. No test exercises this path; the failure is invisible beyond a log warning.

**When to fix:** Sprint 4 hardening phase. Emit an error-level metric (Sentry) on checkpoint write failure so it shows up in on-call dashboards. Optionally re-raise to force ARQ retry (stricter path).

---

### W11 — Missing tests for `page_count=0` and absent `book_id` in AC7

**File:** `apps/api/tests/unit/test_extract_node.py`

**Detail:** The AC explicitly calls out `page_count=0` as a required case (must still write to `books`). No test covers it. Additionally, when `book_id` is absent from state, the write is silently skipped with no log or error — also untested.

**When to fix:** Story 1.3 or next touch of `test_extract_node.py`.

---

### W12 — `worker/jobs/content_pipeline.py` success path writes invalid columns to `lesson_jobs`

**File:** `apps/api/app/workers/jobs/content_pipeline.py` (success path, line ~80)

**Detail:** The success path writes `{"status": "ready", "progress_pct": 100.0, "lesson_package": lesson_package}` to `lesson_jobs`. `"ready"` violates the CHECK constraint (only `completed` is valid); `progress_pct` and `lesson_package` are not columns on `lesson_jobs`. PostgREST rejects the UPDATE; the outer except block marks the lesson as `"failed"` and re-raises for ARQ retry. Every successful pipeline run is recorded as failed. Tracked alongside W1 from the previous review.

**Correct fix:** `{"status": "completed"}` for `lesson_jobs`; `{"status": "ready", "lesson_package": ...}` for `lessons` (or store package in `node_outputs` JSONB of `lesson_jobs`).

**When to fix:** Story 2.6 (`package-builder-node-lesson-ready-websocket-push`) — this is where `lessons.status = "ready"` write belongs anyway.

---

## Deferred from: code review of 1-4-semantic-chunking-node (2026-07-01)

### W16 — `chapter_index` hardcoded to 1 — multi-chapter books collide on repeat ingestion

**File:** `apps/api/app/modules/content/pipeline/graph.py` — `chunk_node` chapters insert

**Detail:** Every call to `chunk_node` inserts a `chapters` row with `chapter_index=1`. If a book has multiple chapters or is re-ingested (the `chapters` table has no unique constraint on `(book_id, chapter_index)` in the current schema), multiple rows accumulate with the same index. Any ordering or deduplication logic downstream that relies on `chapter_index` for ordering will produce incorrect results.

**When to fix:** Story 2.1 (`phase-1-economy-nodes`) when real multi-chapter PDFs are processed. Add a `UNIQUE (book_id, chapter_index)` constraint to the `chapters` table via migration, and pass the actual chapter number from the pipeline state.

---

### W17 — `chunk_id` UUIDs not stored in checkpoint — embed_node must re-query by chapter_id

**File:** `apps/api/app/modules/content/pipeline/graph.py` — `chunk_node` checkpoint

**Detail:** The `chunks.upsert()` return value is discarded, so the DB-generated `chunk_id` UUIDs are never captured. Story 1.5 (`embed_node`) must issue an extra `SELECT chunk_id FROM chunks WHERE chapter_id=? ORDER BY chunk_index` query to get the UUIDs before it can issue `UPDATE chunks SET embedding=...`. This is not a bug (intentional design — `chapter_id` is stored in checkpoint specifically for this purpose) but adds one extra DB round-trip per pipeline run.

**When to fix:** Story 1.5 — capture `[row["chunk_id"] for row in supabase.table("chunks").upsert(rows).execute().data]` in chunk_node and include in checkpoint. This eliminates the re-query in embed_node.

---

## Deferred from: code review of 1-3-structure-detection-node-rule-based-llm-validation (2026-07-01)

### W14 — `raw_text.find(text)` returns TOC offset for repeated headings

**File:** `apps/api/app/modules/content/pipeline/nodes/structure_detection.py:53`

**Detail:** `raw_text.find(text)` always returns the first occurrence. In PDFs with a Table of Contents, heading text appears first in the TOC, so font-strategy candidates get the TOC character offset, not the actual heading position. `build_section_bodies` then slices incorrect body text. Mitigated by LLM validation pass which corrects structural errors. Also: font strategy has no `if text not in candidates` guard (unlike regex loops) — last qualifying block for a given text wins, causing running-headers to overwrite chapter heading levels.

**When to fix:** Sprint 2 — consider using `raw_text.find(text, start)` with an approximate page-offset derived from the font_block's `page` field, or move to an `re.finditer` approach that returns all offsets, keeping the one closest to the expected page range.

---

### W15 — Table PDFs: docling markdown breaks both heading detection strategies

**File:** `apps/api/app/modules/content/pipeline/nodes/structure_detection.py`

**Detail:** When any page has tables, `extract_subprocess.py` replaces `raw_text` with docling markdown (e.g., `## Section`, `### Topic` ATX headings). The font-strategy `raw_text.find(text)` returns -1 for all font spans (markdown wording differs from pdftext spans). The regex strategies match numbered headings (`\d+\.\d+`) but miss ATX markdown headings (`## 1.1 Background`). Result: zero candidates → single-section fallback for all table-containing PDFs. LLM sees first 6000 chars of markdown and can produce structure — this is the primary mitigation.

**When to fix:** Sprint 2 — either (a) run heading detection against the original pdftext output (not docling), or (b) add ATX markdown heading patterns (`^#{1,3}\s+.+`) to Strategy 2 when `raw_text` starts with `#`.

---

### W13 — DALL-E 3 reference in `image_generator_node` TODO (dead provider)

**File:** `apps/api/app/modules/content/pipeline/graph.py` `image_generator_node`

**Detail:** TODO comment references `DalleImageProvider`. DALL-E 3 was shut down May 2026. Correct provider chain: GPT Image 1 Mini → Imagen 4 Fast → text-only fallback.

**When to fix:** Story 2.5 (`image-generator-node-gpt-image-1-mini-imagen-4-fast-text-only`).

---

## Deferred from: code review of 1-5-embeddings-pgvector-storage-node (2026-07-07)

- **W1 — IDOR: lesson_id/chapter_id ownership not re-validated inside embed_node** [`graph.py`] — pre-existing pattern for all pipeline nodes; ownership validation belongs at ARQ job dispatch layer, not inside nodes.
- **W2 — TOCTOU race on idempotency check** [`graph.py`] — ARQ prevents concurrent execution of the same job; architectural lock needed if parallel workers are ever added for the same lesson.
- **W3 — Unbounded chunk SELECT with no LIMIT/pagination** [`graph.py`] — bounded by chapter size in practice; add Supabase row-level pagination in Sprint 2 for large-book support.
- **W4 — Cost ceiling checked after each batch completes (one-batch overshoot ~$0.02)** [`openai.py`] — matches pattern of all other pipeline nodes; pre-add cost estimation before loop in Sprint 2.
- **W5 — IDOR on book_id in books.status update** [`graph.py`] — same as W1, pre-existing pattern.
- **W6 — Internal UUIDs in RuntimeError messages** [`graph.py`] — background worker context, not HTTP response path; sanitize in Sprint 2 hardening pass.
- **W7 — Langfuse generation span not covered by tests (AC12)** [`openai.py`] — provider fully mocked in tests; add provider-level Langfuse integration test in Sprint 2.
- **W8 — EmbeddingsProvider ABC contract not unit-tested** [`providers/base.py`] — verified at import time in production; add contract test in Sprint 2.
- **W9 — config.py `embedding_model` field only tested via mock** [`config.py`] — add `Settings()` instantiation test in Sprint 2 config test pass.
- **W10 — `_BATCH_SIZE = 2048` magic number** [`graph.py`] — add `embedding_batch_size: int` to Settings in Sprint 2 cleanup.
- **W11 — `_EMBED_COST_PER_1K_USD = 0.00002` hardcoded pricing** [`openai.py`] — add `embedding_cost_per_1k_tokens: float` to Settings in Sprint 2.
- **W12 — `openai.py` filename shadows `openai` pip package** [`providers/embeddings/openai.py`] — rename to `openai_provider.py` in Sprint 2; caused sys.modules stub workaround in tests.

## Deferred from: code review of 2-0-pipeline-integration-fixes (2026-07-10)

- Upsert TOCTOU in embed writeback can resurrect deleted rows / clobber newer content — switch to UPDATE-only writeback via RPC (needs new migration). Tier-2/3.
- Extract subprocess stdout fully buffered with no size cap — OOM amplification window grew with the 1500s timeout. Tier-3 #16 (checkpoint/artifact offload to Storage).
- win32 kill path orphans grandchildren (proc.kill() only reaps direct child; no Job Object / taskkill /T). Dev-platform-only; prod is Linux.
- JWT issuer + role claims unverified (audience now checked) — defense-in-depth hardening; requires coordinated change to token minting in tests/E2E.
- embed_node concurrent-run duplicate OpenAI spend + offset-pagination race under concurrent writers — Tier-2 #15 Redis extraction/embed concurrency gate + keyset pagination.
- lesson_package computed and returned but persisted nowhere until package_builder (S2-11) writes lessons.content — ARQ result key retains it for 24h only.
- AC-4 structure guard is a length proxy — duplicated/padded LLM bodies can pass at ≥90% while dropping real content. Tier-3 #18 (boundary-only structure LLM with slice-from-source bodies).
