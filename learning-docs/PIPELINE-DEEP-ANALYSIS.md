# Pipeline Deep Analysis — Where We're Failing, Why It's Slow, How to Fix It

**Date:** 2026-07-09
**Method:** 68-agent workflow — 6 parallel deep-readers (perf / accuracy / orchestration / providers / data-quality / test-gaps) → adversarial verification of every finding against the actual code (one claim refuted by direct measurement) → 3 competing redesign strategies → judge panel → composite plan.
**Verified findings: 55.** Grounded in the live E2E test of 2026-07-08 (3 pages = 7 s; 41 pages = DNF at 600 s; 1120 pages = orphaned 4 GB subprocess at 22 min).

---

## 1. Executive Summary

1. **The pipeline currently cannot run in production at all** — three integration bugs (queue-name mismatch, JWT audience rejection, dead Langfuse v2 API) mean 0% of real uploads execute and embed crashes 100% of the time. Perf work is invisible until these land.
2. **The dominant slowness is docling**: one table anywhere triggers whole-document CPU-torch conversion of ALL pages (extract_subprocess.py:212→229). Scoping docling to table pages is ~27× less docling work and every one of the 3 strategy designs independently converged on it.
3. **The timeout topology is inverted**: ARQ job_timeout (600 s, whole 15-node pipeline) == extract subprocess timeout (600 s), so ARQ always cancels first, extract's `proc.kill()` is dead code, and each retry spawns another 4 GB orphan (up to 3 per lesson).
4. **Accuracy is silently broken even when it "works"**: the structure LLM regenerates section bodies from a 6000-char preview (>99% text loss on a book); font-bold detection never fires (pdftext emits no `bold` key); embed misaligns vectors when any chunk is empty (filtered/unfiltered zip); books >1000 chunks are silently half-embedded (PostgREST row cap).
5. **The 87-green test suite is structurally blind** to all of this: both sides of every integration seam are separately mocked (queue, Langfuse, openai, storage buckets, the extraction subprocess itself).

---

## 2. Failure Map (all verified, file:line)

### A. Blocking outages — pipeline does not run
| ID | Sev | Finding | Where |
|----|-----|---------|-------|
| REL-01 | CRIT | API enqueues to default `arq:queue`; worker consumes `hie:pipeline` → every real upload pending forever | main.py:68 vs workers/main.py:125 |
| SDK-3 | CRIT | `jwt.decode()` without `audience=`; PyJWT 2.13 verifies `aud` by default; Supabase tokens carry `aud='authenticated'` → every real login 401 (verified empirically against pyjwt 2.13) | dependencies.py:54 |
| SDK-1 | CRIT | Langfuse v2 `.trace()/.generation()` called on installed langfuse 4.12.0 (OTel API only) → embed + LLM providers crash AttributeError before the OpenAI call | providers/embeddings/openai.py:61, providers/llm/openai.py:58,99 |
| TSA-6 | HIGH | `lesson-images` bucket referenced in code, never provisioned (404 killed the 3-page run) — buckets now created manually, but nothing ties code→infra | graph.py:213 |

### B. Performance — why 41 pages can't finish in 600 s
| ID | Sev | Finding | Where |
|----|-----|---------|-------|
| PERF-2 | CRIT | One table page → docling whole-document torch conversion of ALL pages | extract_subprocess.py:212, 229-233 |
| PERF-1/REL-02/03 | CRIT | job_timeout == extract timeout (600==600); ARQ CancelledError bypasses `except TimeoutError` → orphaned 4 GB subprocess; retries spawn more orphans | graph.py:184-191, workers/main.py:108 |
| PERF-4 | HIGH | pdfplumber page cache + pypdfium2 page handles never released across the loop → unbounded RSS growth (the 4 GB) | extract_subprocess.py:200-218 |
| PERF-5 | HIGH | pdftext re-parses the ENTIRE pdf a second time for span-level font_blocks of every span in the book | extract_subprocess.py:140,225 |
| PERF-6 | HIGH | Whole result (raw_text + all font_blocks) as one JSON blob over the stdout pipe — 4-5× peak memory amplification | extract_subprocess.py:272, graph.py:185-199 |
| PERF-7 | HIGH | Checkpoint stores full raw_text + font_blocks in lesson_jobs JSONB; every node re-reads/rewrites the growing blob — O(N²) transfer | graph.py:236-242 |
| PERF-8 | HIGH | Images uploaded one-by-one, synchronous supabase client, on the async event loop | graph.py:207-218, core/db.py:44 |
| PERF-9 | MED | Full-page 300 DPI render (~35 MB bitmap) for ANY image incl. tiny logos; crop in PIL not pdfium region render | extract_subprocess.py:101-124 |
| PERF-10 | MED | Extraction fully single-threaded (observed 60% of one core) | extract_subprocess.py |
| PERF-11 | MED | Fixed 600 s regardless of page count — structurally unattainable for big books; retries deterministically re-fail | graph.py:185 |
| ~~PERF-3~~ | — | **REFUTED by measurement**: extract_tables() is NOT ~90% of per-page cost on these PDFs — verifier profiled /tmp/mini.pdf + wininternals.pdf directly | — |

### C. Accuracy — wrong data even on success
| ID | Sev | Finding | Where |
|----|-----|---------|-------|
| ACC-1/DQ-1 | CRIT | Structure LLM prompt truncates to `raw_text[:6000]` yet its output REPLACES rule-based sections → all text beyond 6000 chars silently dropped when the LLM path succeeds. Currently masked only because the langfuse crash disables the LLM path — **fixing SDK-1 activates this data-loss bug** | graph.py:269, 335 |
| ACC-2 | CRIT | `font_blocks[].font.bold` always False — pdftext emits `{name, flags, size, weight}`, never `bold` → font-based heading detection permanently dead | extract_subprocess.py:148-156 |
| ACC-3/DQ-3 | CRIT | Docling replacement desyncs raw_text (markdown) from font_blocks (original pdf) and from the `^`-anchored regexes → structure detection breaks exactly for table-bearing docs → single "Document" section | extract_subprocess.py:227-233, structure_detection.py:24-26 |
| DQ-2 | CRIT | embed select unpaginated → PostgREST 1000-row cap → books >1000 chunks silently half-embedded, then checkpointed as complete | graph.py:520-527 |
| ACC-4 | HIGH | OCR trigger = whole-doc average chars/page → mixed books never OCR their scanned pages; mostly-scanned books OCR-overwrite good pages | extract_subprocess.py:237-249 |
| ACC-5/DQ-4 | HIGH | Page boundaries destroyed (`"\n\n".join`) → chunk page_start/page_end are linear-interpolation guesses stamped section-wide | extract_subprocess.py:222, structure_detection.py:101-103 |
| ACC-6 | HIGH | docling failure → tables silently degrade to jumbled linear text, no signal | extract_subprocess.py:70-72 |
| DQ-5 | HIGH | `_BATCH_SIZE=2048` exceeds OpenAI 300k-token/request embeddings cap → 400 error kills pipeline for books >~580 chunks | graph.py embed |
| SDK-6/DQ-7 | HIGH | embed zips embeddings (from FILTERED texts) against UNFILTERED batch → one empty chunk shifts every later vector onto the wrong chunk | graph.py:544-555 |
| ACC-9 | MED | pypdfium2 emits CRLF; chunking's `\n\n+` paragraph splitter never matches → boundary quality degraded to sentence packing | chunking.py |
| ACC-7 | MED | Image crop math ignores cropbox offset/rotation; no bounds clamping | extract_subprocess.py:111-124 |
| DQ-9/ACC-8 | MED | Heading anchoring via first-occurrence find() + text dedup → TOC becomes the detected structure; text before first heading dropped | structure_detection.py |

### D. Reliability / orchestration
| ID | Sev | Finding |
|----|-----|---------|
| REL-04 | HIGH | Retry semantics backwards: plain `raise` is PERMANENT in arq 0.28 (no retry); only timeouts retry — and those deterministically re-fail |
| REL-05/ACC-01 | HIGH | `lesson_jobs` stuck 'running' + stale error on cancellation; `lessons.status` never updated by worker → frontend polls 'generating' forever |
| REL-06/DQ-8 | HIGH | chunk_node not idempotent: retry duplicates chapters + chunks rows (doubles embedding spend, pollutes RAG) |
| REL-07 | HIGH | Checkpoint writes swallowed (log-and-continue) → "completed" nodes with no durable checkpoint; extract payload will exceed PostgREST limits on big books |
| SDK-2 | CRIT | `with_retry` never retries ANY OpenAI error — openai 2.44 exceptions aren't `httpx.HTTPStatusError` → 429/500/timeout = permanent fail |
| SDK-4/5 | HIGH | Circuit breaker: non-provider errors recorded against 'openai'; HALF_OPEN can never re-open (counter TTL 120 s < 600 s window) and admits unlimited traffic |
| REL-08 | MED | max_jobs=5 × ~4 GB extraction subprocesses = OOM under modest load |
| ARC-01 | MED | Checkpoints only exist for nodes 1-4; `last_node` written but never used as resume pointer; nodes 5-15 uncovered |

---

## 3. Why It's Slow — the causal chain

```
upload 41-page PDF
 └─ extract_node subprocess
     ├─ pypdfium2 text: fast (~0.1 s/page)
     ├─ pdfplumber trigger pass: extract_tables() + .images on every page
     ├─ 300 DPI full-page render for every page with ANY image (~35 MB bitmap each)
     ├─ pdftext: full SECOND parse of the whole pdf (every span in the book)
     ├─ page found with a table → docling: full THIRD parse of ALL pages
     │    through CPU torch layout+table models  ← DOMINANT COST
     ├─ memory never released per page → RSS grows to ~4 GB
     └─ 600 s later: ARQ job_timeout fires FIRST (== extract timeout)
         → CancelledError skips proc.kill() → 4 GB orphan keeps burning CPU
         → ARQ retries → same wall + another orphan → worker starved
```
Measured: 2.3 s/page WITHOUT docling (3-page run); DNF at 600 s WITH docling (41-page run). The docling multiplier is the gap.

---

## 4. The Plan (judge-scored composite; strategies: Minimal-Surgical 9/10, Page-Ledger 7/10, Sharded 6/10)

### TIER 1 — FIX NOW (unblocks green E2E; ~2-3 dev-days)
1. **Queue-name symmetry** — `app/core/queues.py` with `PIPELINE_QUEUE="hie:pipeline"`; use in `create_pool(..., default_queue_name=PIPELINE_QUEUE)` (main.py:68) and `WorkerSettings.queue_name` (workers/main.py:125).
2. **JWT audience** — `audience="authenticated"` in `jwt.decode()` (dependencies.py:54) + tests for right/wrong aud.
3. **Langfuse v4 migration** — replace `.trace()/.generation()` with `start_observation(as_type="generation")` in both providers (+ check tutor state_machine graph.py:480); ALL tracing in try/except so observability can never kill the pipeline; cost accumulation reads `response.usage` directly; pin langfuse major.
4. **Structure data-loss guard — MUST land in same PR as #3**: after LLM returns DocumentStructure, reject if `sum(len(body)) < 0.9 × len(raw_text)` and keep rule-based sections. (#3 activates the LLM path that drops >99% of text.)
5. **Timeout topology + orphan kill** — job_timeout 600→1800 (settings); extract timeout = `min(120 + 1.3×pages, 1500)` ≤ job_timeout−300; `start_new_session=True` + try/**finally** `os.killpg(...SIGKILL)` (finally catches ARQ CancelledError; the current except-TimeoutError never does); `except CancelledError` in content_pipeline_job writes status='failed' under `asyncio.shield`; contract test `job_timeout ≥ extract_timeout + 300`.
6. **embed_node quadruple fix** — (a) filter empty rows ONCE, use for both embed_texts AND writeback zip; (b) paginate IS-NULL select with `.range()` past the 1000-row cap, checkpoint only when final IS-NULL count == 0; (c) batch by ~100k-token budget (not fixed 2048); (d) bulk upsert per batch via `asyncio.to_thread`.
7. **Bucket provisioning as code** — migration inserting source-pdfs / lesson-images / lesson-audio ON CONFLICT DO NOTHING + lifespan startup assertion (fail deploy, not first upload).
8. **Regression tests** — fakeredis queue-symmetry round-trip; langfuse-SDK-surface contract test (real import, assert used methods exist).

### TIER 2 — SPRINT TASK (kills the measured DNFs; ~1 week)
9. **Page-scoped docling** (all 3 strategies converged): collect `table_page_idxs` during the pdfplumber pass → group contiguous runs ±1 page → temp sub-PDF via `PdfDocument.new()+import_pages` → ONE DocumentConverter instance → splice markdown back per page (also fixes the raw_text/font_blocks desync). Fallback: serialize pdfplumber rows as markdown. **~27× less docling work; 41-page DNF → minutes.**
10. **Per-page cost cuts** — `find_tables()` not `extract_tables()` for the trigger; `plumb_page.flush_cache()` + `pdfium_page.close()` every iteration (RSS O(1 page)); DocumentConverter lazy singleton.
11. **Image pre-filter** — skip images <5% page area / <10000 px² before any render; skip full-page render when nothing survives (300 DPI floor untouched).
12. **Accuracy one-liners** — CRLF normalization in `_page_text`; `bold = weight>=600 or flags bit 18 or 'bold' in name`; span filter to bold-or-above-body-mode; chunking `_PARA_SEP → r'(?:\r?\n){2,}'`.
13. **Parallel IO** — image uploads via `asyncio.gather + to_thread` under `Semaphore(8)`; PDF download in to_thread.
14. **Per-page OCR decision** — OCR only pages with `len(text) < threshold` AND raster present; delete whole-doc average trigger.
15. **Extraction concurrency gate** — Redis semaphore: max 2 concurrent extract subprocesses per worker (max_jobs=5 stays for cheap nodes).

### TIER 3 — LATER (Sprint 2 end-state)
16. Checkpoint offload to Storage (`lesson-artifacts/{lesson_id}/extract.json`); node_outputs stores paths only; checkpoint failures RAISE. Kills the O(N²) JSONB blob.
17. Page-ledger contract: per-page provenance, page_offsets + bisect → citation-grade chunk page_start/page_end (needed before Phase-2 RAG citations).
18. Structure LLM demoted to boundary-metadata-only; bodies always sliced locally from raw_text; 2% length-conservation gate (replaces the Tier-1 guard).
19. 4-way page-shard multiprocessing inside the subprocess (only lever that gets 1120 pages under ~15 min; needs #10 first); shard-progress heartbeats on stderr.
20. Region renders via pypdfium2 crop kwarg + cropbox/rotation-correct bbox math.

---

## 5. Projected Outcomes

| PDF | Today | After Tier 1 | After Tier 2 | After Tier 3 |
|-----|-------|--------------|--------------|--------------|
| 3 pages (no tables) | ~40 s to chunk, then embed **crashes** | **green end-to-end ~1 min** | <1 min | <1 min |
| 40 pages (tables) | **DNF (600 s)** | still DNF (docling unscoped) but fails cleanly, no orphan | **~2-4 min ✅** | ~1-2 min |
| 1120-page book | **DNF + 4 GB orphan ×3** | fails cleanly with honest status | ~30-45 min | **~15-20 min** |

*(PRD's 2-5 min Phase-A target is per-chapter; per-chapter ingestion should stay the product default. Full-book is the stress case.)*

---

## 6. Why the 87-green suite caught none of this

| Bug | Blinding mock | Contract test that would catch it |
|-----|--------------|----------------------------------|
| Queue mismatch | AsyncMock arq pool on producer side; worker never spun up | fakeredis round-trip: enqueue via app pool → assert job visible on `WorkerSettings.queue_name` |
| Langfuse v4 | `Langfuse` class itself patched (test_langfuse_core.py:47,61,77,97) | import real SDK; assert `hasattr` for every method the providers call |
| JWT aud | Test tokens minted WITHOUT aud claim | round-trip test with `aud='authenticated'` in the token |
| Docling timeout | extraction subprocess never executed — stdout is canned JSON (test_extract_node.py patches create_subprocess_exec at 160,184,210,244,271,306,346) | tiny real-PDF fixture through the real subprocess with a time budget |
| Orphan leak | No test covers cancellation/timeout ordering | assert `job_timeout ≥ extract_timeout + headroom`; cancellation test asserting child reaped |
| Missing bucket | MagicMock storage accepts any bucket name | manifest test: every `from_("...")` literal in code ∈ provisioned-bucket list |
| Missing openai dep | conftest.py:17-27 `sys.modules.setdefault("openai", MagicMock())` session-wide | runtime-deps test importing every provider module with NO stubs |

---

*Full agent transcripts: `~/.claude/projects/.../workflows/wf_fc5e5bd1-c95/journal.jsonl` (68 agents, 55 verified findings, 1 refuted).*
