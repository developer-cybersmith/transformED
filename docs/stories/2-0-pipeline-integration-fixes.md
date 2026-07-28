# Story 2-0 — Pipeline Integration Fixes (Tier 1: unblock green E2E)

**Status:** done (5-agent review passed 2026-07-10 — 2 decisions resolved, 21 patches applied, 7 deferred)
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
- **Test:** round-trip test proving a job enqueued via the app's pool settings is visible on the queue name the worker consumes (no live Redis required — assert both sides resolve to the same constant, plus an arq-level integration test).

### AC-2 JWT audience verification
- `apps/api/app/dependencies.py` `jwt.decode()` called with `audience="authenticated"`.
- **Tests:** (a) token WITH `aud="authenticated"` is accepted; (b) token with WRONG aud is rejected 401; (c) token with NO aud is rejected 401 (PyJWT `verify_aud` triggers on required audience).

### AC-3 Langfuse v4 migration
- All provider tracing calls use the langfuse 4.x API (`start_observation(as_type="generation")` / `update()` / `end()`); zero calls to removed v2 methods (`.trace()`, `.generation()`).
- Every tracing call is wrapped so an observability failure can NEVER fail the pipeline (try/except around tracing only, never around the provider call itself).
- Cost accumulation decoupled from tracing: reads `response.usage` directly.
- `apps/api/app/modules/tutor/state_machine/graph.py` checked for the same dead API (Dev 4 file — if affected, flag, do not fix cross-module).
- langfuse major version pinned in `pyproject.toml`.
- **Test:** SDK-surface contract test importing the REAL langfuse package and asserting every method name the providers call exists on the client/observation objects; behavioral test: raising tracer cannot fail provider calls.

### AC-4 Structure data-loss guard (atomic with AC-3)
- After the structure LLM returns `DocumentStructure`, the node computes `sum(len(section.body))`; if < 0.9 × `len(raw_text)`, the LLM result is REJECTED and the rule-based structure is kept (warning logged).
- **Test:** LLM mock returning tiny bodies for a large raw_text → rule-based result wins; LLM mock returning faithful bodies → LLM result wins.

### AC-5 Timeout topology + orphan kill
- `job_timeout` settings-driven (`settings.arq_job_timeout_s`, default 1800) in `WorkerSettings`.
- Extract subprocess timeout settings-driven and page-aware: `min(120 + 1.3 × page_estimate, 1500)`, never exceeding `job_timeout − 300`; `page_estimate = max(1, pdf_bytes // 30_000)` byte heuristic.
- Subprocess spawned with `start_new_session=True` (start_new_session on POSIX only; win32 uses `proc.kill()`); cleanup in `try/finally` (not `except TimeoutError`) using process-group SIGKILL (`os.killpg`) guarded by `sys.platform`, then `await proc.wait()` — so ARQ `CancelledError` also reaps the child.
- `content_pipeline_job` catches `CancelledError`, writes `lesson_jobs.status='failed'` + error under `asyncio.shield`, then re-raises.
- **Tests:** contract test `job_timeout ≥ extract_timeout_max + 300`; cancellation test asserting the child process is reaped when the node task is cancelled.

### AC-6 embed_node quadruple fix
- (a) Empty-content chunks filtered ONCE into a single filtered list used for BOTH `embed_texts` input AND the writeback pairing — misalignment impossible.
- (b) IS-NULL select paginated with `.range()` loops past PostgREST's 1000-row cap; checkpoint written only after a final IS-NULL re-check over non-empty-content chunks returns 0.
- (c) Batching by token budget (~100k tokens using `token_count`), not fixed 2048 chunks.
- (d) Embedding writeback is one bulk upsert per batch via `asyncio.to_thread`, with `on_conflict="chunk_id"` and six echoed columns (`chunk_id`, `chapter_id`, `content`, `chunk_index`, `embedding`, `embedding_metadata`) — PostgREST upsert validates NOT NULL constraints on the incoming row BEFORE conflict arbitration, so the NOT NULL columns must be echoed or every writeback 23502s even when the row already exists.
- **Tests:** empty-chunk-in-batch alignment test (each vector lands on the correct chunk_id); >1000-row pagination test; token-budget split test; bulk-upsert call-shape test.

### AC-7 Bucket provisioning as code
- New migration inserting `source-pdfs`, `lesson-images`, `lesson-audio` into `storage.buckets` with `ON CONFLICT (id) DO UPDATE SET public = excluded.public` — idempotent AND reconciles the visibility of manually-created buckets (applied migrations untouched).
- Buckets are private (all four, per review decision D1 — lesson content is the paid deliverable, served via signed URLs only); visibility asserted at startup.
- FastAPI lifespan startup (and ARQ worker startup) asserts all code-referenced buckets exist and are private — fail deploy, not first upload.
- **Test:** bucket-manifest test asserting every `from_("...")` literal in `app/` is in the provisioned list.

### AC-8 Regression tests for the E2E outage class
- fakeredis (or constant-symmetry) queue round-trip test.
- Runtime-deps contract test importing every provider module with NO sys.modules stubs (subprocess-isolated so the conftest stub can't mask it).

### AC-9 Schema-valid completion write (added in review)
- On pipeline success, `content_pipeline_job` writes `lesson_jobs.status='completed'` + `completed_at` — a value permitted by the table's status CHECK constraint. No out-of-schema status literal may be written on any terminal path (success or failure); a CHECK-violating write is silently swallowed and strands the row in `running`.
- **Test:** status-validity test parametrized across all `_update_lesson_status` call sites; completion-path test asserting `status='completed'` and a non-null `completed_at`.

## Dev Notes — cross-module flags (do not fix here)

- **→ Dev 4 (AC-3 spillover):** `apps/api/app/modules/tutor/state_machine/graph.py:480` still calls the
  removed langfuse v2 API `get_langfuse().trace(...)`. Its own try/except swallows the AttributeError, so
  the FSM works but **all tutor dispatch tracing is silently a no-op under langfuse 4.x in production**.
  `tests/test_tutor_graph.py:615` asserts `.trace` on a MagicMock stub, so the suite gives false confidence.
  Migrate to `start_observation(...)`/`create_event(...)` in Dev 4's lane (same pattern as
  `providers/llm/openai.py` after this story).
- **Storage note:** `avatar-clips` (heygen provider) was code-referenced but unprovisioned — now included in
  the AC-7 migration and lifespan assertion as of this story.
- **→ Dev 2 (D1 — media access change):** `lesson-images` and `lesson-audio` are now PRIVATE buckets
  (flipped live 2026-07-10 + migration reconciles). The frontend must fetch all lesson media via the
  signed-URL endpoint (media router, `GET /api/media/signed-url`) instead of public bucket URLs —
  `getPublicUrl(...)` links will 400/403.
- **Suite-boot deps note:** `python-multipart` and `email-validator` are runtime deps of the FastAPI
  form-upload and pydantic `EmailStr` paths that only surface at app import; the `filterwarnings`
  entries in pyproject exist so the unit suite can boot the app factory without drowning in
  third-party deprecation noise — all three trace to suite-boot needs, not feature code.

## Out of scope (Tier 2/3 — separate stories)
Page-scoped docling, per-page cache release, image pre-filter, parallel uploads, per-page OCR, checkpoint offload, page-ledger, multiprocessing shards.

## Definition of Done
- All ACs have explicit passing tests; full unit suite green.
- Live E2E: 3-page PDF through real stack (FastAPI + ARQ + Supabase + OpenAI) reaches `lesson_jobs.status='completed'`-equivalent for Phase A (extract→structure→chunk→embed), `chunks.embedding IS NOT NULL` for all non-empty-content chunks, `books.status='ready'`.
- 5-agent code review before merge.

### Review Findings (5-agent gate, 2026-07-10)

- [x] [Review][Decision] Public buckets expose paid lesson content — `lesson-images`/`lesson-audio` are `public=true` with zero storage RLS policies (unauthenticated fetch of the paid deliverable, CDN-cached); migration's ON CONFLICT DO NOTHING also never reconciles the `public` flag of manually-created buckets and the lifespan check verifies names only. Decide: keep public-CDN posture (then reconcile flags + document) vs signed URLs like `avatar-clips`. **RESOLVED (D1): signed-URL posture — all four buckets private; live buckets flipped 2026-07-10; migration now `DO UPDATE SET public = excluded.public`; startup assertion verifies visibility; Dev 2 flagged in Dev Notes.**
- [x] [Review][Decision] Story file amended inside implementation commit f9036c0 (Dev Notes section) — letter violation of "story and implementation never share a commit" (intent honored: 855c4d8 story-only and first). Decide: rebase-split vs recorded waiver in the PR. **RESOLVED: waiver — story-only commit 855c4d8 was first; Dev Notes amendment accepted in implementation commit; future amendments get docs(story) commits.**
- [x] [Review][Patch] Embed batching lacks the 2048-items-per-request cap and per-input (~8191-token) guard; oversized-chunk test certifies behavior the real API 400s [graph.py embed packing]
- [x] [Review][Patch] CancelledError handler's shield wrapped in `except Exception` — a re-cancellation (BaseException) escapes uncaught [workers/jobs/content_pipeline.py:154]
- [x] [Review][Patch] Sync paginated selects run on the ARQ event loop (fetch + completion re-fetch) — wrap `_fetch_unembedded_chunks` in `asyncio.to_thread` [graph.py:581]
- [x] [Review][Patch] Timeout invariant unenforced at runtime — add Settings model_validator (`arq_job_timeout_s >= extract_timeout_cap_s + 300`) + clamp `_compute_extract_timeout` to ≥1s; env override currently yields 0/negative wait_for [config.py, graph.py]
- [x] [Review][Patch] `get_langfuse()` unwrapped in provider `__init__` — bad LANGFUSE_* env crashes providers mid-job, violating AC-3's never-fail clause; add try/except + None-tolerant `_safe_trace` + behavioral raising-tracer tests [providers/*/openai.py]
- [x] [Review][Patch] `_safe_trace` swallows tracing outages at DEBUG — raise to WARNING [providers/*/openai.py]
- [x] [Review][Patch] Upsert-shape test does not assert the echoed NOT-NULL columns — reverting the echo passes green and fails prod with 23502 [tests/unit/test_embed_node.py]
- [x] [Review][Patch] Cost-ceiling path writes schema-illegal `status='cost_limit_exceeded'` (CHECK violation swallowed → row stuck `running`, no retry); write `failed` + error, parametrize status-validity test across all `_update_lesson_status` call sites (full ceiling behavior = S2-13) [workers/jobs/content_pipeline.py:132]
- [x] [Review][Patch] Stale `"ready"` docstring + ARQ result literal contradict the f9866d1 fix [workers/jobs/content_pipeline.py:36-39,120]
- [x] [Review][Patch] AC-4 guard: empty `raw_text` bypasses (0<0 False → hallucinated sections adopted); add empty-guard + exactly-90% boundary test + pin duplication-inflation behavior [graph.py structure_node]
- [x] [Review][Patch] `await proc.wait()` in finally unshielded — second cancellation interrupts the reap [graph.py extract_node]
- [x] [Review][Patch] Bucket probe fragile parsing (`b["name"]` KeyError path) — defensive extraction + factor `_assert_buckets` helper [app/main.py:89-91] — done: `app/core/storage.py::assert_required_buckets`
- [x] [Review][Patch] ARQ worker startup has no bucket assertion — call the shared helper in workers/main.py startup [workers/main.py]
- [x] [Review][Patch] Lifespan bucket assertion has no behavioral test — test the helper with mocked list_buckets (missing → RuntimeError; all present → pass) [tests/unit/test_bucket_manifest.py]
- [x] [Review][Patch] Manifest scanner silently ignores unresolvable bucket identifiers — fail loudly on unresolved [tests/unit/test_bucket_manifest.py]
- [x] [Review][Patch] runtime-deps test imports only 2 provider modules — enumerate app/providers/**/*.py dynamically (AC-8 letter) [tests/unit/test_runtime_deps.py]
- [x] [Review][Patch] Vacuous `test_enqueue_default_matches_worker_queue_via_arq_settings` (asserts its own assignment) — delete; add worker-side source-text assertion so literal drift is caught both sides [tests/unit/test_queue_symmetry.py]
- [x] [Review][Patch] fakeredis round-trip can silently skip in CI — assert HAS_FAKEREDIS when CI env set [tests/unit/test_queue_symmetry.py]
- [x] [Review][Patch] Story text amendments: AC-6d 6-column upsert shape, AC-6b "non-empty chunks" wording, DoD "all non-empty chunks", AC-3 failure-path test clause, AC-5 page_estimate byte-heuristic + platform-conditional session note, drop AC-1 "where feasible", completion-write AC, deps/filterwarnings trace note [this file]
- [x] [Review][Defer] Upsert TOCTOU can resurrect deleted rows / clobber newer content — UPDATE-only writeback via RPC — deferred, Tier-2/3 (needs migration)
- [x] [Review][Defer] Extract stdout fully buffered, no size cap (OOM amplification window grew with timeout) — deferred, Tier-3 #16 artifact offload
- [x] [Review][Defer] win32 kill path orphans grandchildren (no Job Object/taskkill /T) — deferred, dev-only; prod is Linux
- [x] [Review][Defer] JWT issuer + role claims unverified (defense-in-depth) — deferred, beyond story scope; needs coordinated token-minting update
- [x] [Review][Defer] embed_node concurrent-run duplicate OpenAI spend + offset-pagination race — deferred, Tier-2 #15 Redis concurrency gate + keyset pagination
- [x] [Review][Defer] lesson_package computed then persisted nowhere until package_builder lands — deferred, S2-11 scope (ARQ result retains it 24h)
- [x] [Review][Defer] AC-4 length-proxy can pass duplicated/padded bodies — deferred, Tier-3 #18 boundary-only structure LLM
