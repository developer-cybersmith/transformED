# Story 2-0 — Pipeline Integration Fixes (Tier 1: unblock green E2E)

**Sprint:** 2 (pre-work — blocks all Sprint 2 stories)
**Owner:** Dev 1
**Branch:** `sprint2/s2-0-pipeline-integration-fixes`
**Source:** Live E2E test 2026-07-08 + 68-agent deep analysis (`learning-docs/PIPELINE-DEEP-ANALYSIS.md`, 55 verified findings)

## Context

The Sprint 1 ingestion pipeline passes 87/87 unit tests but cannot run in production: the live E2E test proved 0% of real uploads execute (queue mismatch), all real logins 401 (JWT aud), and embed crashes 100% (dead Langfuse v2 API). This story lands the Tier-1 composite plan: make the pipeline execute, fail cleanly, and embed correctly. Performance work (page-scoped docling etc.) is Tier 2 — explicitly out of scope here.

## Acceptance Criteria

### AC-1 Queue-name symmetry
- New `apps/api/app/core/queues.py` exporting `PIPELINE_QUEUE = "hie:pipeline"` as the single source of truth.
- `apps/api/app/main.py` builds the enqueue pool with `create_pool(..., default_queue_name=PIPELINE_QUEUE)`.
- `apps/api/app/workers/main.py` `WorkerSettings.queue_name` references `PIPELINE_QUEUE` (no literal duplication).
- **Test:** round-trip test proving a job enqueued via the app's pool settings is visible on the queue name the worker consumes (no live Redis required — assert both sides resolve to the same constant, plus an arq-level integration test where feasible).

### AC-2 JWT audience verification
- `apps/api/app/dependencies.py` `jwt.decode()` called with `audience="authenticated"`.
- **Tests:** (a) token WITH `aud="authenticated"` is accepted; (b) token with WRONG aud is rejected 401; (c) token with NO aud is rejected 401 (PyJWT `verify_aud` triggers on required audience).

### AC-3 Langfuse v4 migration
- All provider tracing calls use the langfuse 4.x API (`start_observation(as_type="generation")` / `update()` / `end()`); zero calls to removed v2 methods (`.trace()`, `.generation()`).
- Every tracing call is wrapped so an observability failure can NEVER fail the pipeline (try/except around tracing only, never around the provider call itself).
- Cost accumulation decoupled from tracing: reads `response.usage` directly.
- `apps/api/app/modules/tutor/state_machine/graph.py` checked for the same dead API (Dev 4 file — if affected, flag, do not fix cross-module).
- langfuse major version pinned in `pyproject.toml`.
- **Test:** SDK-surface contract test importing the REAL langfuse package and asserting every method name the providers call exists on the client/observation objects.

### AC-4 Structure data-loss guard (atomic with AC-3)
- After the structure LLM returns `DocumentStructure`, the node computes `sum(len(section.body))`; if < 0.9 × `len(raw_text)`, the LLM result is REJECTED and the rule-based structure is kept (warning logged).
- **Test:** LLM mock returning tiny bodies for a large raw_text → rule-based result wins; LLM mock returning faithful bodies → LLM result wins.

### AC-5 Timeout topology + orphan kill
- `job_timeout` settings-driven (`settings.arq_job_timeout_s`, default 1800) in `WorkerSettings`.
- Extract subprocess timeout settings-driven and page-aware: `min(120 + 1.3 × page_estimate, 1500)`, never exceeding `job_timeout − 300`.
- Subprocess spawned with `start_new_session=True`; cleanup in `try/finally` (not `except TimeoutError`) using process-group SIGKILL (`os.killpg`) guarded by `sys.platform`, then `await proc.wait()` — so ARQ `CancelledError` also reaps the child.
- `content_pipeline_job` catches `CancelledError`, writes `lesson_jobs.status='failed'` + error under `asyncio.shield`, then re-raises.
- **Tests:** contract test `job_timeout ≥ extract_timeout_max + 300`; cancellation test asserting the child process is reaped when the node task is cancelled.

### AC-6 embed_node quadruple fix
- (a) Empty-content chunks filtered ONCE into a single filtered list used for BOTH `embed_texts` input AND the writeback pairing — misalignment impossible.
- (b) IS-NULL select paginated with `.range()` loops past PostgREST's 1000-row cap; checkpoint written only after a final IS-NULL count returns 0.
- (c) Batching by token budget (~100k tokens using `token_count`), not fixed 2048 chunks.
- (d) Embedding writeback is one bulk upsert per batch (`chunk_id`, `embedding`, `embedding_metadata`, `on_conflict="chunk_id"`) via `asyncio.to_thread`.
- **Tests:** empty-chunk-in-batch alignment test (each vector lands on the correct chunk_id); >1000-row pagination test; token-budget split test; bulk-upsert call-shape test.

### AC-7 Bucket provisioning as code
- New migration inserting `source-pdfs`, `lesson-images`, `lesson-audio` into `storage.buckets` with `ON CONFLICT DO NOTHING` (applied migrations untouched).
- FastAPI lifespan startup asserts all code-referenced buckets exist — fail deploy, not first upload.
- **Test:** bucket-manifest test asserting every `from_("...")` literal in `app/` is in the provisioned list.

### AC-8 Regression tests for the E2E outage class
- fakeredis (or constant-symmetry) queue round-trip test.
- Runtime-deps contract test importing every provider module with NO sys.modules stubs (subprocess-isolated so the conftest stub can't mask it).

## Dev Notes — cross-module flags (do not fix here)

- **→ Dev 4 (AC-3 spillover):** `apps/api/app/modules/tutor/state_machine/graph.py:480` still calls the
  removed langfuse v2 API `get_langfuse().trace(...)`. Its own try/except swallows the AttributeError, so
  the FSM works but **all tutor dispatch tracing is silently a no-op under langfuse 4.x in production**.
  `tests/test_tutor_graph.py:615` asserts `.trace` on a MagicMock stub, so the suite gives false confidence.
  Migrate to `start_observation(...)`/`create_event(...)` in Dev 4's lane (same pattern as
  `providers/llm/openai.py` after this story).
- **Storage note:** `avatar-clips` (heygen provider) was code-referenced but unprovisioned — now included in
  the AC-7 migration and lifespan assertion as of this story.

## Out of scope (Tier 2/3 — separate stories)
Page-scoped docling, per-page cache release, image pre-filter, parallel uploads, per-page OCR, checkpoint offload, page-ledger, multiprocessing shards.

## Definition of Done
- All ACs have explicit passing tests; full unit suite green.
- Live E2E: 3-page PDF through real stack (FastAPI + ARQ + Supabase + OpenAI) reaches `lesson_jobs.status='completed'`-equivalent for Phase A (extract→structure→chunk→embed), `chunks.embedding IS NOT NULL` for all chunks, `books.status='ready'`.
- 5-agent code review before merge.
