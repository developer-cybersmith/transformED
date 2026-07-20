# Epic 1: Content Generation Pipeline

| Field | Value |
|---|---|
| Epic ID | E-01 |
| Status | Planned |
| Owner | Dev 1 |
| Target Sprints | Sprint 1–2 (Weeks 2–5) |
| Priority | P0 — blocks all other epics |

---

## Problem Statement

TransformED's core value proposition is fully automated lesson generation from a PDF upload. Without a reliable, cost-bounded, crash-recoverable pipeline that produces a complete lesson package, nothing else in the product can be built or tested. This epic delivers that pipeline.

**Added 2026-07-13 (Learner Mode):** the pipeline must also support a content-depth **tier** (T1 full / T2 standard / T3 critical-topics-only) selected per lesson, since students vary in how much time they have per session. This amends nodes 11 (`lesson_planner`) and 12 (`slide_generator`) below rather than introducing new nodes — see the tier column added to the Phase B.2 table and the new Learner Mode rows in Definition of Done. Full task breakdown lives in `docs/dev1-tracker.md`'s Sprint 2 section (S2-LM1 through S2-LM5).

---

## Goal / Success Metric

> **Any college PDF (up to 50 pages) produces a complete lesson package in under 15 minutes at a cost of $3.00 or less per lesson, with zero manual intervention.**

Secondary metrics:
- Pipeline resumes from last successful node on crash (no full reprocess)
- Every node uses `with_retry()` — no silent failures
- Provider can be swapped (OpenAI → Anthropic) via config, not code

---

## User Stories

- As a **student**, I can upload a PDF and receive a complete interactive lesson without waiting more than 15 minutes.
- As a **developer**, I can swap the LLM provider without touching pipeline logic.
- As a **developer**, I can inspect the status of any in-flight or failed job from the admin panel.
- As a **platform operator**, I am confident total LLM spend per lesson will not exceed $3.00 under any normal input.
- As a **developer**, if a pipeline worker crashes mid-run, the job resumes from the last completed node — not from scratch.
- As a **student**, I can choose a lesson depth tier (T1 full-depth / T2 standard / T3 critical-topics-only refresher) matching how much time I have for this session.

---

## Pipeline Node Specification

Nodes execute in two physically separate phases. Each node checkpoints to `lesson_jobs.last_node` before returning.

### Phase A — Book Ingestion (runs once per book, ~2–5 min)

| # | Node | Input | Output | Key Constraint |
|---|---|---|---|---|
| 1 | `extract` | PDF bytes | raw text + page map | pypdfium2 + pdftext (PyMuPDF/`fitz` is BANNED — AGPL-3.0); never pass full book to LLM |
| 2 | `structure` | raw text | chapter/section outline | hierarchical chunking |
| 3 | `chunk` | outline | semantic chunks (≤800 tokens) | overlap 10% |
| 4 | `embed` | chunks | vector(1536) stored inline in `chunks.embedding` | Embed at ingestion only — NEVER regenerate stored embeddings |

### Phase B — Chapter Generation (per chapter, student-triggered, ~5–15 min)

**Phase B.1 — Economy nodes (ALL run in parallel, `settings.llm_mini`):**

| # | Node | Input | Output | Key Constraint |
|---|---|---|---|---|
| 5 | `summarise_segment` | chunks | segment summaries | MUST complete for ALL segments before Phase B.2 starts |
| 6 | `quiz_generator` | summaries | MCQ JSON per segment | 3 questions per segment |
| 7 | `segment_complexity` | summaries | complexity score per segment | float 0–1 |
| 8 | `jargon_extractor` | chunks | jargon term list + definitions | deduped across segments |
| 9 | `intervention_msgs` | complexity + jargon | pre-generated intervention strings A/B/C | built once — no GPT at runtime |
| 10 | `narration_script` | slide JSON + summaries | narration scripts with timestamp hints | per-slide |

**Phase B.2 — Premium nodes (sequential — start only after ALL Phase B.1 complete):**

| # | Node | Input | Output | Key Constraint |
|---|---|---|---|---|
| 11 | `lesson_planner` | segment summaries from Phase B.1 + `tier` | lesson plan JSON | GPT-4o; input is summaries NOT raw chapter text (5× token savings); **tier-aware (Learner Mode):** targets T1 20–25 / T2 12–15 / T3 6–8 slides, T3 outline limited to critical topics only |
| 12 | `slide_generator` | lesson plan (tier-scoped) | slide JSON array | respects the per-segment slide budget `lesson_planner` set for the request's tier — does not re-derive tier logic independently |

**Phase B.3 — Media nodes:**

| # | Node | Input | Output | Key Constraint |
|---|---|---|---|---|
| 13 | `tts_node` | narration scripts | `.mp3` per segment + `narration.timestamps` JSON | Sarvam Bulbul v2 → Azure TTS → Browser Speech (fallback chain) |
| 14 | `image_generator` | slide content | slide images | GPT Image 1 Mini → Imagen 4 Fast → text-only |
| 15 | `package_builder` | all Phase B outputs | `lesson_package.json` + asset manifest | final artifact consumed by player |

> **Critical execution constraint:** Phase B.2 CANNOT start until ALL segments complete Phase B.1. `lesson_planner` receives segment summaries — NEVER raw chapter text. Violating this silently causes a 5× cost overrun.

---

## Technical Scope

| Layer | Files / Modules |
|---|---|
| Pipeline graph + all node implementations | `apps/api/app/modules/content/pipeline/graph.py` (all 15 node functions defined here, not one file per node — `nodes/` holds only extracted helper modules too large to inline: `chunking.py`, `extract_subprocess.py`, `structure_detection.py`) |
| Checkpointing | Inline in each node function in `graph.py` — writes `lesson_jobs.last_node` + `node_outputs` (no separate `checkpoint.py` module) |
| ARQ worker | `apps/api/app/workers/main.py` (`WorkerSettings`) + `apps/api/app/workers/jobs/content_pipeline.py` (job entry point) |
| Provider abstraction | `apps/api/app/providers/base.py` (ABCs) + `apps/api/app/providers/llm/openai.py`, `providers/tts/`, `providers/image/`, `providers/avatar/` |
| Retry + circuit breaker | `apps/api/app/core/retry.py` — `with_retry()`; `apps/api/app/core/circuit_breaker.py` — `is_circuit_open()` |
| Storage | `apps/api/app/core/storage.py` (bucket assertion) + `apps/api/app/core/db.py` (Supabase client) |
| Cost tracking | `apps/api/app/core/cost_tracker.py` — `accumulate_cost()` / `check_ceiling()` |
| DB migrations | `supabase/migrations/` — `lessons`, `lesson_jobs`, `books`, `chapters`, `chunks` (inline `embedding vector(1536)`). `embeddings` table was dropped in `20260625000000` — embeddings are now inline in `chunks.embedding`. `lessons.tier` pending via S2-LM2 (Learner Mode). |

**State management:** LangGraph `MemorySaver` (in-memory per invocation). `PostgresSaver` is **BANNED** — conflicts with Supabase PgBouncer + asyncpg. Custom `lesson_jobs` checkpointing only.

**Worker queue:** ARQ backed by Redis. Celery is explicitly rejected.

**Cost ceiling enforcement:** `cost_tracker.py` accumulates token costs per node; raises `CostLimitExceeded` if projected total exceeds $3.00, which triggers a graceful job failure (not a crash).

---

## Out of Scope (Phase 2)

- RAG tutor Q&A (embeddings are stored in this epic but the retrieval chain is not built)
- Multi-language PDF support
- PDF > 50 pages
- Video slide generation

> **Note:** `PostgresSaver` is **permanently BANNED** — not deferred to Phase 2. It conflicts with Supabase PgBouncer + asyncpg. `lesson_jobs` + `MemorySaver` is the final checkpointing solution.

---

## Dependencies

| Dependency | Status |
|---|---|
| Sprint 0 infra (Railway, Supabase, Redis) | Done |
| Shared API contracts (`lesson_package.json` schema) | Done (Sprint 0) |
| Sarvam AI API key provisioned (primary TTS) | Must be done before Sprint 1 Day 1 |
| Supabase storage bucket `lesson-assets` created | Must be done before Sprint 1 Day 1 |
| `lesson_jobs` DB table with `last_node` column | Migration in this epic |

---

## Definition of Done

- [ ] All 15 nodes implemented, individually unit-tested with mocked LLM responses
- [ ] Full pipeline integration test passes with a real 10-page PDF
- [ ] Full pipeline integration test passes with a real 50-page PDF in < 15 min
- [ ] Cost for a 50-page PDF does not exceed $3.00 (verified with cost tracker logs)
- [ ] Job crashed at node 8, restarted, and resumed from node 8 (not node 1) — documented test result
- [ ] `with_retry()` wraps every LLM call; circuit breaker tested with simulated provider outage
- [ ] Provider swap (OpenAI → Anthropic) demonstrated via env var change, no code change
- [ ] All node outputs conform to `lesson_package.json` schema (Pydantic validation passing)
- [ ] ARQ worker visible in admin job monitor
- [ ] No hardcoded API keys; all secrets via Railway env vars
- [ ] **(Learner Mode)** `tier` field present on the frozen lesson contract (JSON schema + TS + Pydantic), reviewed and signed off by all 4 devs
- [ ] **(Learner Mode)** `lessons.tier` column migrated, enum-constrained (`T1`/`T2`/`T3`), default `T2`
- [ ] **(Learner Mode)** Three pipeline runs (T1/T2/T3) against the same test chapter each produce a slide count inside that tier's range (T1 20–25, T2 12–15, T3 6–8)

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TTS API latency blows 15-min budget | Medium | High | Async parallel TTS calls; cache identical narration text |
| Image generation cost spikes | Medium | High | GPT Image 1 Mini → Imagen 4 Fast → text-only fallback. DALL-E 3 is shut down (May 2026). |
| LLM output fails Pydantic schema | High | Medium | `with_retry()` with structured output; fallback to JSON repair |
| 50-page PDF exceeds context window | Low | High | Hierarchical chunking enforces ≤800 token input per LLM call |
| ARQ job loss on Redis restart | Low | High | Redis persistence (AOF) enabled in Railway config |
