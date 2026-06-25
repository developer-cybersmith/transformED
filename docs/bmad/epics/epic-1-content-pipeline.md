# Epic 1: Content Generation Pipeline

| Field | Value |
|---|---|
| Epic ID | E-01 |
| Status | Planned |
| Owner | Dev 1 |
| Target Sprints | Sprint 1â€“2 (Weeks 2â€“5) |
| Priority | P0 â€” blocks all other epics |

---

## Problem Statement

HIE's core value proposition is fully automated lesson generation from a PDF upload. Without a reliable, cost-bounded, crash-recoverable pipeline that produces a complete lesson package, nothing else in the product can be built or tested. This epic delivers that pipeline.

---

## Goal / Success Metric

> **Any college PDF (up to 50 pages) produces a complete lesson package in under 15 minutes at a cost of $3.00 or less per lesson, with zero manual intervention.**

Secondary metrics:
- Pipeline resumes from last successful node on crash (no full reprocess)
- Every node uses `with_retry()` â€” no silent failures
- Provider can be swapped (OpenAI â†’ Anthropic) via config, not code

---

## User Stories

- As a **student**, I can upload a PDF and receive a complete interactive lesson without waiting more than 15 minutes.
- As a **developer**, I can swap the LLM provider without touching pipeline logic.
- As a **developer**, I can inspect the status of any in-flight or failed job from the admin panel.
- As a **platform operator**, I am confident total LLM spend per lesson will not exceed $3.00 under any normal input.
- As a **developer**, if a pipeline worker crashes mid-run, the job resumes from the last completed node â€” not from scratch.

---

## Pipeline Node Specification

Nodes execute in strict order. Each node checkpoints to `lesson_jobs.last_node` before returning.

| # | Node | Input | Output | Key Constraint |
|---|---|---|---|---|
| 1 | `extract` | PDF bytes | raw text + page map | PyMuPDF; never pass full book to LLM |
| 2 | `structure` | raw text | chapter/section outline | hierarchical chunking |
| 3 | `chunk` | outline | semantic chunks (â‰¤800 tokens) | overlap 10% |
| 4 | `embed` | chunks | vector embeddings stored in Supabase | batch embed; stored for Phase 2 RAG |
| 5 | `lesson_planner` | outline | lesson plan JSON | GPT-4o; 1 LLM call per section |
| 6 | `slide_generator` | lesson plan | slide JSON array | max 20 slides/lesson |
| 7 | `summarise_segment` | chunks | segment summaries | per-segment, not full-book |
| 8 | `quiz_generator` | summaries | MCQ JSON per segment | 3 questions per segment |
| 9 | `segment_complexity` | summaries | complexity score per segment | float 0â€“1 |
| 10 | `jargon_extractor` | chunks | jargon term list + definitions | deduped across segments |
| 11 | `intervention_messages` | complexity + jargon | pre-generated intervention strings A/B/C | built once â€” no GPT at runtime |
| 12 | `narration_generator` | slide JSON + summaries | narration scripts with timestamp hints | per-slide |
| 13 | `tts_node` | narration scripts | `.mp3` files + `narration.timestamps` JSON | ElevenLabs or OpenAI TTS |
| 14 | `image_generator` | slide JSON | slide images (DALL-E or static fallback) | optional; fallback to CSS slides |
| 15 | `package_builder` | all outputs | `lesson_package.json` + asset manifest | final artifact consumed by player |

---

## Technical Scope

| Layer | Files / Modules |
|---|---|
| Pipeline graph | `backend/pipeline/graph.py` |
| Node implementations | `backend/pipeline/nodes/*.py` (one file per node) |
| Checkpointing | `backend/pipeline/checkpoint.py` â€” writes `lesson_jobs.last_node` |
| ARQ worker | `backend/workers/pipeline_worker.py` |
| Provider abstraction | `backend/llm/providers.py` (OpenAI / Anthropic adapters) |
| Retry + circuit breaker | `backend/llm/resilience.py` â€” `with_retry()`, `CircuitBreaker` |
| Storage | `backend/storage/lesson_store.py` â€” Supabase bucket + DB writes |
| Cost tracking | `backend/pipeline/cost_tracker.py` â€” tracks token spend per job |
| DB migrations | `supabase/migrations/` â€” `lesson_jobs`, `lesson_packages`, `embeddings` tables |
| ARQ job definition | `backend/workers/jobs.py` â€” `generate_lesson_job` |

**State management:** LangGraph `MemorySaver` (in-memory per invocation). `PostgresSaver` is deferred to Phase 2.

**Worker queue:** ARQ backed by Redis. Celery is explicitly rejected.

**Cost ceiling enforcement:** `cost_tracker.py` accumulates token costs per node; raises `CostLimitExceeded` if projected total exceeds $3.00, which triggers a graceful job failure (not a crash).

---

## Out of Scope (Phase 2)

- RAG tutor Q&A (embeddings are stored in this epic but the retrieval chain is not built)
- `PostgresSaver` for LangGraph distributed checkpointing
- Multi-language PDF support
- PDF > 50 pages
- Video slide generation

---

## Dependencies

| Dependency | Status |
|---|---|
| Sprint 0 infra (Railway, Supabase, Redis) | Done |
| Shared API contracts (`lesson_package.json` schema) | Done (Sprint 0) |
| ElevenLabs / OpenAI TTS API key provisioned | Must be done before Sprint 1 Day 1 |
| Supabase storage bucket `lesson-assets` created | Must be done before Sprint 1 Day 1 |
| `lesson_jobs` DB table with `last_node` column | Migration in this epic |

---

## Definition of Done

- [ ] All 15 nodes implemented, individually unit-tested with mocked LLM responses
- [ ] Full pipeline integration test passes with a real 10-page PDF
- [ ] Full pipeline integration test passes with a real 50-page PDF in < 15 min
- [ ] Cost for a 50-page PDF does not exceed $3.00 (verified with cost tracker logs)
- [ ] Job crashed at node 8, restarted, and resumed from node 8 (not node 1) â€” documented test result
- [ ] `with_retry()` wraps every LLM call; circuit breaker tested with simulated provider outage
- [ ] Provider swap (OpenAI â†’ Anthropic) demonstrated via env var change, no code change
- [ ] All node outputs conform to `lesson_package.json` schema (Pydantic validation passing)
- [ ] ARQ worker visible in admin job monitor
- [ ] No hardcoded API keys; all secrets via Railway env vars

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TTS API latency blows 15-min budget | Medium | High | Async parallel TTS calls; cache identical narration text |
| Image generation cost spikes | Medium | High | DALL-E is optional; CSS fallback enabled by default |
| LLM output fails Pydantic schema | High | Medium | `with_retry()` with structured output; fallback to JSON repair |
| 50-page PDF exceeds context window | Low | High | Hierarchical chunking enforces â‰¤800 token input per LLM call |
| ARQ job loss on Redis restart | Low | High | Redis persistence (AOF) enabled in Railway config |

