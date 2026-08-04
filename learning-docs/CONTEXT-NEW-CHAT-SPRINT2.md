# TransformED AI — New Chat Context Document (Sprint 2 Handoff)

**Generated:** 2026-07-13
**Purpose:** Paste this document at the start of a fresh Claude chat to resume Sprint 2 development with zero context loss.
**Branch at time of writing:** `main` (commit `8650b98`) — Sprint 1 + all hardening is merged. Sprint 2 has not started.

---

## 1. HOW TO USE THIS DOCUMENT

Read this entire document before doing anything else. Every constraint here is non-negotiable and actively enforced. Nothing here is a suggestion — it reflects architectural decisions, security requirements, legal constraints (AGPL bans), production bugs already fixed, and a hard-won lesson about git history rewrites (§9). Reintroducing a fixed bug or violating a hard rule will result in PR rejection.

For the full rule set, always cross-reference `E:\transformED-corp\CLAUDE.md` — it is the canonical source of truth and is checked into the repo (loaded automatically as project instructions in Claude Code).

When in doubt about any constraint: stop, re-read CLAUDE.md, and ask for clarification rather than making an assumption.

---

## 2. PROJECT MISSION & GOAL

**TransformED AI** is an AI-powered adaptive learning platform. A student uploads a chapter PDF; the system generates a complete lesson with slides, narration audio, quiz questions, jargon glossary, and intervention messages. During the lesson, a 7-state tutor monitors engagement via a Cognitive Engagement Score (CES) and intervenes when the student is distracted or fatigued.

**Week 10 goal:** First paying student completes a full session (~2026-08-20).

**Current status (2026-07-13):**
- Sprint 0: Complete
- Sprint 1 (Phase A ingestion): Complete AND **live-validated three times over** (3-page PDF, 41-page PDF with tables, full 1,120-page book) — see §8.
- **Sprint 1 hardening (Stories 2-0, 2-0b): Complete.** A live E2E test on 2026-07-08 proved the "complete" Sprint 1 pipeline was actually 0% functional in production (queue mismatch, JWT rejection, dead observability SDK, docling performance collapse). All fixed, adversarially reviewed, and merged into `main` as **PR #72** on 2026-07-13.
- **Sprint 2 (Phase B, 11 generation nodes): NOT STARTED — 0/14 tasks.** This is what you're picking up.
- Frontend (Dev 2), assessment/analytics (Dev 3), and tutor FSM (Dev 4) are all **ahead of backend Sprint 2** — they built against mocked lesson content per the project's own anti-deadlock rule. This is expected, not a problem, but it means Sprint 2 is now the critical path everyone else is waiting on.

**What exists right now:** a student can `POST` a PDF to `/api/content/lessons` and the system extracts text, detects structure, chunks it, and embeds every chunk into pgvector — proven live at three scales (90 s / 8.3 min / 66 min). **What does NOT exist yet:** lesson planning, slide generation, quiz generation, narration, TTS audio, image generation, or the final `LessonPackage` assembly. That's all of Sprint 2.

---

## 3. LOCKED TECHNOLOGY STACK

Unchanged from Sprint 1 — see `CLAUDE.md` for the full table (backend FastAPI, ARQ not Celery, Next.js 14, Supabase Postgres+pgvector, Railway Redis, LangGraph pinned `==1.2.6`, GPT-4o/4o-mini via `settings.llm_*` aliases — never hardcode model strings).

**One change since Sprint 1:** Langfuse is now pinned `>=4.0.0,<5.0.0` (was `>=2.0.0`) — the v2 API (`.trace()`, `.generation()`) is gone; providers use `start_observation(as_type="generation")`. See §10.

---

## 4. NON-NEGOTIABLE HARD RULES

All Sprint 1 rules from `CLAUDE.md` still apply unchanged (no Celery, no PyMuPDF/fitz, no PostgresSaver, 300 DPI images, subprocess-isolated PDF parsing, never hardcode models, never regenerate stored chunk embeddings, cost ceiling $3/lesson, story-first gate, 5-agent code review). **Additions learned the hard way during Sprint 1 hardening:**

20. **Queue name must be imported from `app/core/queues.py` (`PIPELINE_QUEUE = "hie:pipeline"`)** on BOTH the enqueue side (`app/main.py`, `create_pool(..., default_queue_name=PIPELINE_QUEUE)`) and the worker side (`app/workers/main.py`, `WorkerSettings.queue_name`). A literal-string duplication here once meant 0% of real uploads were ever picked up by the worker.
21. **JWT verification must include `audience="authenticated"`** in `jwt.decode()`. Without it, every real Supabase-issued token (which always carries `aud="authenticated"`) is rejected — this once caused 100% of real logins to fail while all unit tests stayed green (test tokens didn't carry an `aud` claim).
22. **All Langfuse tracing calls must be wrapped so a tracing failure can NEVER fail the pipeline** (`_safe_trace` pattern in both providers). A bad Langfuse key must degrade to no-op tracing, not crash `embed_node`.
23. **Storage buckets are provisioned as code** (`supabase/migrations/20260710000000_storage_buckets.sql`) and asserted at both API and worker startup (`app/core/storage.py::assert_required_buckets`) — fail deploy, not first upload. **`lesson-images` and `lesson-audio` are PRIVATE** (signed URLs only — lesson content is the paid deliverable). Frontend fetches media via the signed-URL endpoint, never `getPublicUrl`.
24. **ARQ `job_timeout` and the extract-subprocess timeout must never be equal.** `job_timeout` (`settings.arq_job_timeout_s`, default 1800) must be `>= extract_timeout_cap_s + 300` (enforced by a Pydantic `model_validator` in `config.py`) — otherwise ARQ cancels the job before the subprocess's own cleanup runs, orphaning multi-GB child processes. Subprocess cleanup lives in `try/finally` (not `except TimeoutError`), using `os.killpg` on POSIX.
25. **`lesson_jobs.status` may ONLY be one of `pending/running/completed/failed`** (schema CHECK constraint). Do not write `"ready"`, `"cost_limit_exceeded"`, or any other literal — it silently violates the constraint, the write is swallowed, and the row sticks at `running` forever with ARQ never retrying. Use `status="failed"` with a descriptive `error` prefix instead (e.g. `"cost_ceiling_exceeded: ..."`).
26. **`embed_node`'s writeback MUST echo `chapter_id`, `content`, `chunk_index`** in the upsert payload alongside `chunk_id`/`embedding`/`embedding_metadata`. Postgres validates `NOT NULL` on the candidate tuple *before* `ON CONFLICT` arbitration — omitting these columns fails every real writeback with `23502`, even though every `chunk_id` already exists (a mocked unit test cannot catch this; it only surfaces against a real DB).
27. **Never run `git filter-repo` (or any full-repo history rewrite) with other unrelated local branches present in your clone.** It rewrites every local ref by default, not just the ones you scope, and can silently disconnect your branch's shared ancestry with `main`. See §9 for the full story — this already happened once and cost real time to fix.

---

## 5. TEAM OWNERSHIP

Unchanged from Sprint 1 (`CLAUDE.md` §21). **Dev 1 (you) now also owns:** `app/core/queues.py`, `app/core/storage.py` (new since hardening). Git user: `developer1-cybersmith`.

**Anti-deadlock note relevant to Sprint 2:** Dev 2/3/4 have built substantial features against mocked lesson content. Do NOT silently change the shape of anything Sprint 2 produces without checking `packages/shared/lesson_package.schema.json` / `lesson.ts` (frozen contracts, 4-dev review required) — a 5-agent discovery pass on 2026-07-13 confirmed the frontend mock already matches the frozen contract exactly (one tiny drift: mock `lesson_id`/`book_id`/`chapter_id` use slug strings, schema wants `format: "uuid"` — cheap fix, note it if you touch that file). Look for `[DEV1-SPRINT2-PENDING]` comments across the frontend player stack and `apps/api/app/workers/jobs/content_pipeline.py` / `app/core/pubsub.py` — these mark exact spots that need reconciling once `package_builder` (S2-11) is real. **Known live gap:** Dev 4's tutor `_segment_intervention_messages` currently silently returns `{}` (no crash) because the stub `package_builder_node` output has no `segments[]` key — this MUST be fixed by S2-11, not patched around elsewhere.

---

## 6. DATABASE SCHEMA

Applied and FROZEN migrations (never modify):
- `20260611000000_initial_schema.sql`
- `20260625000000_chunks_inline_embedding.sql`
- `20260630000000_unique_attempt_constraints.sql` (Dev 3)
- `20260702000000_dpdp_user_consents.sql` (Dev 3)
- `20260703000000_onboarding_unique_constraint.sql` (Dev 3)
- `20260703010000_add_analytics_consent.sql` (Dev 3)
- `20260710000000_storage_buckets.sql` (Dev 1 — provisions `source-pdfs`, `lesson-images`, `lesson-audio`, `avatar-clips`, all private)

Table shapes for `books`, `lessons`, `lesson_jobs`, `chapters`, `chunks` are unchanged from Sprint 1 — see the original context doc (`learning-docs/CONTEXT-NEW-CHAT.md`) §6 for full column tables, still accurate. `lesson_jobs.status` CHECK is `pending/running/completed/failed` only (rule 25 above).

---

## 7. THE 15-NODE PIPELINE — CURRENT STATUS

```
Phase A (DONE, hardened, live-validated):
  upload → extract → structure → chunk → embed
```
```
Phase B1 — parallel economy nodes (settings.llm_mini) — YOUR NEXT WORK, S2-1:
  summarise_segment × N   quiz_generator × N   segment_complexity × N
  jargon_extractor × N    intervention_messages × N   narration_generator × N
  (ALL must finish before Phase B2 starts)

Phase B2 — sequential premium nodes:
  lesson_planner  ← input: segment SUMMARIES from Phase B1, NOT raw chapter text
                     (this is the single most cost-critical constraint in the
                      whole pipeline — violating it is a silent 5× cost overrun)
  slide_generator ← input: lesson outline from lesson_planner

Phase C — media, sequential:
  tts_node (Sarvam → Azure → Browser)
  image_generator (GPT Image 1 Mini → Imagen 4 Fast → text-only)
  package_builder (assembles final LessonPackage, MUST match
                    app/schemas/lesson.py::LessonPackage / the frozen contract —
                    see §5 above for the known gap this must close)
```

`app/modules/content/pipeline/graph.py` currently has nodes 1-4 fully implemented (~1115 lines total) and nodes 5-15 as stubs (`return []`/`{}` placeholders) starting around line 958. Extract itself was substantially rewritten in the hardening pass (page-scoped docling — see §12) — it's a different, faster implementation than what Sprint 1 originally shipped, still the same public contract (`raw_text`, `page_count`, `image_files`, `font_blocks`, plus new additive keys `tables_detected`, `docling_pages`).

---

## 8. SPRINT 1 + HARDENING — WHAT WAS ACTUALLY BUILT

### Sprint 1 base (as originally delivered)
- `POST /api/content/lessons` — magic-byte + MIME validation, 50 MB cap, 5/min rate limit, full rollback, 202 + deduplicated job id.
- `extract_node` — pypdfium2 + pdftext + pdfplumber (table trigger) + docling (page-scoped, see below) + Tesseract, subprocess-isolated.
- `structure_node` — font clustering + regex + GPT-4o-mini validation, now with a **data-loss guard**: LLM output is only adopted if it covers ≥90% of `raw_text`'s length; otherwise the rule-based structure is kept (the LLM prompt only sees a 6000-char preview, so unguarded adoption silently drops the rest of the chapter).
- `chunk_node` — cl100k_base, 512 target/64 overlap tokens, never mid-sentence.
- `embed_node` — text-embedding-3-small → pgvector(1536), token-budget batching (not fixed chunk-count), paginated past PostgREST's 1000-row cap, filter-once-then-align to prevent embedding/chunk misalignment (rule 26 above).

### The hardening campaign (Stories 2-0 and 2-0b — READ THESE FILES FIRST if anything is unclear)
- `docs/stories/2-0-pipeline-integration-fixes.md` — Tier 1: makes the pipeline actually run. Queue fix, JWT fix, Langfuse v4 migration, structure guard, timeout topology, embed quadruple fix, bucket provisioning, regression tests. 5-agent BMAD review: 21 patches applied, 2 decisions resolved (private buckets; a process waiver), 7 items deferred.
- `docs/stories/2-0b-page-scoped-docling.md` — Tier 2: makes it fast. Root cause was one table page anywhere triggering whole-document ML conversion of every page. Fixed by scoping docling to contiguous table-page runs only. **Measured** (not estimated): 41-page table-bearing PDF went from "never finishes" (>600s) to ~206s extraction, ~8.3 min full upload-to-completed. Full 1,120-page book: **66 minutes, 1,379/1,379 chunks embedded**, unattended.
- `learning-docs/PIPELINE-DEEP-ANALYSIS.md` — the 68-agent deep analysis (55 verified findings) that produced the Tier 1/2/3 plan. Tier 3 (page sharding, checkpoint offload, citation-grade provenance) is NOT started — separate future work, not blocking Sprint 2.

### Live validation record (all real infrastructure, no mocks)
| Run | Result |
|---|---|
| 3-page PDF | ~90 s, completed |
| 41-page PDF (tables) | 8.3 min, completed, 52/52 chunks embedded |
| 1,120-page book | 66 min, completed, 1,379/1,379 chunks embedded |
| **Final re-verification after merge to `main`** (2026-07-13) | ~2.5 min, completed, 4/4 chunks embedded — confirmed on the *actual pushed commit*, not an isolated branch |

---

## 9. THE GIT HISTORY SAGA — READ THIS BEFORE TOUCHING GIT

This section exists so you don't get confused or try to "fix" something that's already resolved.

**What happened:** `main` had diverged massively from Dev 1's branch chain — ~200 teammate commits (frontend, assessment, analytics) landed via normal PRs while Dev 1's Sprint 1 work stayed on isolated feature branches. Merging required care to avoid destroying teammates' work (never force-replace `main`).

**A real secret leak happened and was fixed:** a documentation file (`learning-docs/CONTEXT-NEW-CHAT.md`, the Sprint 1 version) had a real Supabase anon key + project URL committed in cleartext. It was purged from git history via `git filter-repo`. **This had a side effect worth knowing:** `filter-repo` rewrites the ENTIRE local repo by default, not just the branches you scope — it silently disconnected the shared-ancestry link between Dev 1's branches and the real `main`, which caused a second round of confusing "can't automatically merge" conflicts across ~40 unrelated files. This was fixed by tracing the exact commit that introduced the secret, fixing only that one commit via a scoped `git rebase --onto`, and replaying the rest of the untouched history on top — NOT by re-running filter-repo.

**Current state (2026-07-13): fully resolved.** `main` is at commit `8650b98`, PR #72 is merged, the secret is verified purged from all history (`git log --all -S"<the-old-key>"` returns nothing), ancestry is correct, and 207/207 tests pass on the real merged `main`. **You do not need to redo any of this.** If you ever need to purge a secret again: identify the exact tainted commit, fix ONLY that commit via targeted rebase, never run a repo-wide history rewrite tool while other unrelated local branches exist in your clone.

**Branch naming going forward:** `sprint2/s2-{N}-{slug}`, always branched fresh off `main` (which now has everything), never stacked on a previous task's branch. Story-first: story file committed alone and pushed before any implementation commit.

---

## 10. BUGS FIXED — NEVER REINTRODUCE

All Sprint 1 bugs from the original context doc (P1-P12, E1-E2) still apply — see `learning-docs/CONTEXT-NEW-CHAT.md` §9 for the full list (checkpoint swallowing, hardcoded dimensions, zip() truncation, empty-chunk filtering, etc.). **New ones found during hardening:**

- **Queue-name mismatch** (rule 20) — 0% of uploads ever executed.
- **JWT missing `audience=`** (rule 21) — 100% of real logins rejected.
- **Langfuse v2 API on an installed v4 SDK** — embed crashed 100% of the time; fixed via `_safe_trace` wrapper pattern, provider `__init__` also wrapped (a bad Langfuse key must not crash provider construction).
- **Structure LLM silent data loss** (rule 3/22 above) — the 90%-coverage guard.
- **Timeout tie causing orphaned subprocesses** (rule 24) — a single timed-out extraction could leak a 4 GB child process; fixed via `try/finally` + `killpg` + non-equal timeout budgets.
- **Missing storage buckets** — 404 on any PDF with images; fixed via migration + startup assertion (rule 23).
- **`embed_node` upsert NOT NULL violation** (rule 26) — every real writeback would 500 in production; only caught by testing against a REAL database, not mocks.
- **Cost-ceiling path writing an illegal status literal** (rule 25) — silently stranded the job at `running` forever.
- **Storage upload rate-limiting under concurrent bursts** — a 545-image book (the full 1,120-page book) hit Supabase Storage rate limits at 8-way concurrency; fixed with 5-attempt exponential backoff + reduced concurrency to 4.
- **docling image placeholder overwriting OCR text** — `export_to_markdown`'s default `image_placeholder="<!-- image -->"` is non-empty, so a scanned page inside a table-run's ±1 page expansion would have its real Tesseract OCR text silently overwritten with placeholder junk. Fixed: `image_placeholder=""` (load-bearing empty string).

---

## 11. PROVIDER ABSTRACTION PATTERN

Unchanged in shape from Sprint 1 (`providers/base.py` ABCs, `providers/llm/openai.py`, `providers/embeddings/openai.py`) — see original context doc §10. **What changed:** all Langfuse tracing calls now go through a `_safe_trace()` helper in both providers so a tracing failure (bad key, host down, SDK version mismatch) can NEVER fail the actual provider call. `get_langfuse()` construction itself is also wrapped — if it fails, the provider sets its internal langfuse handle to `None` and all tracing becomes a silent no-op, while the OpenAI call still succeeds normally. **When you build the Sprint 2 provider calls (TTS, image generation), follow this exact same wrapping pattern — do not call Langfuse directly without the safe wrapper.**

---

## 12. NEW ARCHITECTURAL DECISIONS (since Sprint 1)

**Decision: Page-scoped docling, not whole-document.** Original extraction converted the ENTIRE PDF through docling's ML models the moment ANY page had a table. Now: pdfplumber's cheap `find_tables()` flags table pages, contiguous runs are grouped (±1 page guard), a temporary sub-PDF of just those pages is built via `pypdfium2.PdfDocument.new().import_pages(...)`, and ONE lazily-created `DocumentConverter` is reused across runs. Non-run pages keep their pypdfium2 text verbatim, spliced back via docling's per-page provenance (`export_to_markdown(page_no=k, image_placeholder="")`). Docling failure on a run falls back to serializing pdfplumber's raw table rows as markdown — never crashes. This is why a 41-page book went from "never finishes" to ~206s.

**Decision: Private storage buckets, signed URLs.** Originally `lesson-images`/`lesson-audio` were public (fast, simple). Reviewed and reversed: lesson content is the paid product — public buckets meant anyone with a guessable URL could access paid content for free, unrevocably (CDN-cached). Now all four buckets are private; media is served via `GET /api/media/signed-url`.

---

## 13. ENVIRONMENT SETUP — CURRENT STATE

**Everything is installed and working.** The Python venv lives INSIDE WSL (`/mnt/e/transformED-corp/apps/api/.venv`) — this is a Windows machine; ALL Python commands must go through `wsl -e bash -lc "..."` from Git Bash/PowerShell, or run directly if you're already inside a WSL shell.

### Services
| Service | Start command |
|---|---|
| Redis | `docker start redis-dev` (Docker Desktop must be open) |
| API | `wsl -e bash -lc "cd /mnt/e/transformED-corp/apps/api && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env"` |
| Worker | `wsl -e bash -lc "cd /mnt/e/transformED-corp/apps/api && .venv/bin/arq app.workers.main.WorkerSettings"` |

**Before starting services, ALWAYS check for stale processes first** — a stale hour-old uvicorn silently serving requests (instead of your freshly-started one) caused a false-positive test result during Sprint 1 wrap-up. Check with:
```bash
wsl -e bash -lc 'ss -ltnp 2>/dev/null | grep :8000; ps -eo pid,lstart,args | grep -E "uvicorn app.main|bin/arq app.workers" | grep -v grep'
```
Kill anything unexpected by PID before starting fresh (`kill -9 <pid>`), then verify port 8000 is free before launching.

### All Python packages installed (previously missing, now present)
`tiktoken`, `docling` (+ torch, heavy install), `pytesseract`, `openai` (real SDK, not the test-only stub), `fakeredis` (dev dep, for the queue round-trip test), `python-multipart`, `email-validator`. System binary `tesseract-ocr` is optional (only needed for scanned-page OCR testing, not for the standard text-PDF path).

### Auth for local testing
Real Supabase auth login isn't needed — JWTs are verified locally. Mint a test token directly:
```python
import time, jwt
claims = {"sub": "<a real user_id from your users table>", "email": "...", "role": "authenticated",
          "aud": "authenticated", "iat": int(time.time()), "exp": int(time.time()) + 2*3600}
token = jwt.encode(claims, SUPABASE_JWT_SECRET, algorithm="HS256")
```
**`aud="authenticated"` is required** (rule 21) — omitting it will pass locally-minted tests but doesn't represent what real users experience; always include it.

### Demo kit (built during hardening, useful for any live check)
- `scripts/demo/ingest_demo.py` — uploads a PDF, prints a live timeline through completion.
- `scripts/demo/ask_the_book.py` — semantic Q&A over an already-ingested book's embedded chunks (proves the vectors are real and useful).
- `demo-assets/sample-chapter.pdf` — a proven 41-page test chapter (gitignored, copyrighted source material — local only).

---

## 14. TEST SUITE STATE

**207 passed, 0 failed, 0 skipped** (up from 87 at the end of raw Sprint 1). Run with:
```bash
wsl -e bash -lc "cd /mnt/e/transformED-corp/apps/api && .venv/bin/python -m pytest tests/unit/ -q"
```
New test files since Sprint 1: `test_jwt_audience.py`, `test_langfuse_sdk_contract.py`, `test_provider_tracing_resilience.py`, `test_queue_symmetry.py`, `test_timeout_contract.py`, `test_bucket_manifest.py`, `test_runtime_deps.py`, `test_pipeline_tier1.py`, `test_extract_subprocess.py` (42 tests alone, covering the page-scoped docling rewrite). Two Dev 3 test files (`test_quiz_endpoint.py`, `test_teachback_endpoint.py`) still fail collection on a missing conftest stub pattern — not your problem, flagged for Dev 3, don't let it block your suite runs (they're outside `tests/unit/`).

---

## 15. SPRINT 2 — DETAILED TASK LIST (START HERE)

> **Goal:** All 11 generation nodes producing a valid `LessonPackage` JSONB from an ingested chapter.
> **Cost ceiling rule:** every provider call → `cost_tracker.accumulate_cost()` immediately after; `check_ceiling()` before expensive nodes; on breach: downshift providers, complete the lesson, write `status="failed"` with a `cost_ceiling_exceeded:` prefix (NEVER a bare `cost_limit_exceeded` status literal — rule 25).
> **Circuit breaker:** `is_circuit_open(provider_key)` before every external call — already built (`core/circuit_breaker.py`), just wire it into each new provider call.

**Phase 1 Economy nodes (S2-1 through S2-6) — run in PARALLEL per segment via LangGraph `Send()` fan-out. ALL must complete before Phase 2 starts.**

- **S2-1 `summarise_segment`** — `settings.llm_mini`. 2-3 sentence summary per segment, consumed by `lesson_planner` INSTEAD of raw text (the 5× cost-savings constraint — see Phase 2 below). AC: summary ≤100 words.
- **S2-2 `segment_complexity`** — `settings.llm_mini`. Output validates against `app.schemas.SegmentComplexity`; `intervention_sensitivity` in [0.0, 1.0].
- **S2-3 `quiz_generator`** — `settings.llm_mini`. Exactly 4 options per question, `correct_index` in range, `min_length=4` enforced.
- **S2-4 `jargon_extractor`** — `settings.llm_mini`. `JargonEntry` list, no empty terms/definitions.
- **S2-5 `intervention_messages`** — `settings.llm_mini`. Exactly 3×3 messages (distraction/confusion/fatigue). **CRITICAL: pre-generated at pipeline time — zero GPT calls at intervention runtime** (PRD §10). This is what feeds the currently-empty `{}` gap in Dev 4's tutor service (§5 above) — get the output shape right the first time.
- **S2-6 `narration_generator`** — `settings.llm_mini`. Narration script per segment, ≤15 words/sec pacing, tone matches `SegmentComplexity.narration_style`.

**Phase 2 Premium nodes (S2-7, S2-8) — sequential, only after ALL Phase 1 nodes complete for ALL segments.**

- **S2-7 `lesson_planner`** — `settings.llm_lesson_planner` (highest-cost node). **Input MUST be segment summaries from S2-1, NOT raw chapter text.** This is the single most important constraint in the whole pipeline — violating it silently 5×s the cost of every lesson. Use `complete_structured()` with a Pydantic response model. Output validates as `LessonMetadata`.
- **S2-8 `slide_generator`** — `settings.llm_slide_generator`. Input: lesson outline from S2-7. Output: `Slide` list per segment (`slide_id`, `title`, `bullets`, `image_url` nullable).

**Phase 3 Media nodes (S2-9, S2-10, S2-11) — sequential, after Phase 2.**

- **S2-9 `tts_node`** — Sarvam AI Bulbul v2 → Azure TTS → Browser Speech fallback chain. ElevenLabs is REMOVED (banned, replaced). 403 (not 401) = Sarvam auth failure; 429 body inspection matters (`rate_limit_exceeded_error` retryable, `insufficient_quota_error` NOT retryable). Wire `is_circuit_open("sarvam")`. Pipeline NEVER fails over TTS — Browser Speech always available. Set `audio_provider` to `"sarvam"/"azure"/"browser"` (the frozen contract's `AudioProvider` enum — do not use `"elevenlabs"`, it was renamed and removed everywhere).
- **S2-10 `image_generator`** — GPT Image 1 Mini → Imagen 4 Fast → text-only fallback. **DALL-E 3 is BANNED** (shut down May 2026). Falls back to `image_url=None` near the cost ceiling — never fails the pipeline over images.
- **S2-11 `package_builder`** — assembles everything into the final `LessonPackage`. **Build this via `app.schemas.lesson.LessonPackage` (the Pydantic model that already correctly mirrors the frozen contract) — NOT a raw dict**, unlike the current stub. `LessonPackage.model_validate(assembled)` must pass. Write `lessons.content` + `lessons.status="ready"` + `lesson_jobs.status="completed"` + `completed_at`. Emit `lesson_ready` WebSocket push matching `packages/shared/types/ws.ts` exactly — coordinate with Dev 4. **This is the node that closes the tutor-intervention gap flagged in §5** — get `segments[].interventions` right.

**Also in scope for Sprint 2:**
- **S2-12** — WebSocket `lesson_ready` push, coordinate shape with Dev 4.
- **S2-13** — Cost ceiling enforcement wired into every new node (the mechanism already exists, just needs calling).
- **S2-14** — Eval harness against 5 representative PDFs (short/long/dense-text/table-heavy/image-heavy) — you already have real test PDFs from the hardening campaign (`/tmp/mini.pdf`, `/tmp/excerpt.pdf`, `demo-assets/sample-chapter.pdf`) plus real timing baselines to build this against.

---

## 16. BMAD PROCESS RULES (unchanged, still mandatory)

**Story-first gate:** create `docs/stories/{N}-{M}-{slug}.md` with all ACs defined → commit ONLY the story file → push → verify it's the first commit on the branch → only then write code.

**5-agent code review before merge:** Story Quality, Blind Hunter (Security), Test Coverage, AC Completeness, Process Integrity. The Story 2-0 review is the reference example for what this looks like in practice (2 decisions escalated, 21 patches, 7 deferred) — see the story file for the exact findings format.

**Branch naming — OVERRIDDEN for Sprint 2:** CLAUDE.md's normal "one branch per task, fresh off `main`" rule is explicitly overridden for Sprint 2 by user decision (2026-07-13). **All Sprint 2 tasks (S2-1 through S2-14) share ONE branch: `sprint2/phase-b-generation-nodes`.** Create it once, off `main`, at the very start of S2-1 — then reuse it for every subsequent task; do not branch fresh per task. The BMAD story-first gate still applies per task (each task's story file still committed and pushed before that task's implementation), it just lands on this same shared branch rather than a new one each time.

**Sprint tracker auto-update rule:** whenever a task completes, update `docs/dev1-tracker.md`'s checkbox + dashboard + header date in the same response, without being asked.

---

## 17. KEY FILE MAP (updated)

| Purpose | Path |
|---|---|
| Queue name single source of truth | `apps/api/app/core/queues.py` |
| Bucket assertion helper | `apps/api/app/core/storage.py` |
| Pipeline graph (nodes 1-4 real, 5-15 stubs) | `apps/api/app/modules/content/pipeline/graph.py` |
| Extraction subprocess (page-scoped docling) | `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py` |
| Pydantic lesson schemas (use this for S2-11) | `apps/api/app/schemas/lesson.py` |
| Frozen JSON contract | `packages/shared/lesson_package.schema.json` |
| Frozen TS contract | `packages/shared/types/lesson.ts` |
| Tier-1 story (read for full rationale) | `docs/stories/2-0-pipeline-integration-fixes.md` |
| Tier-2 story (read for full rationale) | `docs/stories/2-0b-page-scoped-docling.md` |
| Deep analysis + 3-tier plan | `learning-docs/PIPELINE-DEEP-ANALYSIS.md` |
| Sprint 1 original context (still useful for schema tables, DB details) | `learning-docs/CONTEXT-NEW-CHAT.md` |
| Demo scripts | `scripts/demo/ingest_demo.py`, `scripts/demo/ask_the_book.py` |
| Dev 1 sprint tracker | `docs/dev1-tracker.md` |
| Cross-team master tracker | `docs/master-tracker.md` |

---

## 18. IMMEDIATE FIRST ACTION

1. Read this whole document, then skim `docs/stories/2-0-pipeline-integration-fixes.md` and `2-0b-page-scoped-docling.md` for full rationale on anything unclear above.
2. Check environment: Docker Desktop open, `docker start redis-dev`, check for stale processes (§13) before starting fresh API + worker.
3. Confirm you're on `main` at the latest commit (`git fetch && git log -1 origin/main`), then story-first gate for **S2-1**: `docs/stories/2-1-phase1-economy-nodes.md`, commit alone, push. Create the shared branch `sprint2/phase-b-generation-nodes` off `main` (once — this is the ONE branch for all of Sprint 2, see the branch-naming override in §16), THEN implement.
4. Build all 6 Phase-1 economy nodes together (they're designed to run in parallel via `Send()` fan-out) — S2-1 through S2-6.

*End of context document. If anything here conflicts with CLAUDE.md, CLAUDE.md wins. If anything here conflicts with the story files (2-0, 2-0b), the story files win (they're the more detailed, reviewed source).*
