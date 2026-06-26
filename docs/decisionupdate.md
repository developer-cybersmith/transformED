# TransformED AI — PRD Decisions Update
**Date:** June 18, 2026  
**Status:** Pre-Sprint 1 — distribute to all developers before Sprint 0 closes  
**Authority:** Supersedes conflicting entries in PRD v1.0 (June 10, 2026)

---

## How to read this document

Each entry below is tagged with one of three states:

- 🔴 **BLOCKER** — must be resolved before any related code is written
- 🟡 **UPDATED** — PRD decision has changed; update your implementation plan
- 🟢 **CONFIRMED** — discussed and explicitly locked; no change from PRD but worth noting

Where a PRD section is referenced (e.g. `§6.3`), that section should be treated as overridden by this document until a formal PRD v1.1 is issued.

---

## Sprint 0 Blockers

### 1. DALL-E 3 is dead — replace immediately
**Status:** 🔴 BLOCKER  
**PRD reference:** §6.3 (image provider), Node 10  
**Affects:** Dev 1 (pipeline), anyone building Node 10

DALL-E 3 API was permanently shut down on May 12, 2026. Any code targeting the DALL-E 3 endpoint will fail on the first call. The PRD fallback chain (`DALL-E 3 → stock illustration → text-only slide`) must be replaced.

**Updated provider chain:**
```
Primary:   GPT Image 1 Mini  (gpt-image-1-mini)   $0.005/image
Fallback:  Imagen 4 Fast     (Vertex AI India)     $0.020/image  ← DPDP-safe
Last:      Text-only slide   (no image)
```

**Action required:** Update PRD §6.3 and Node 10 provider config before building the image generation node.

---

### 2. Node execution order — Node 3 must run before Node 1
**Status:** 🔴 BLOCKER  
**PRD reference:** §9 (pipeline node list), §22 (LangGraph scaffold)  
**Affects:** Dev 1 (LangGraph StateGraph)

The PRD lists nodes 1–11 which implies Node 1 (lesson planner) runs first. This is incorrect. Node 1 must receive segment summaries as input, which means Node 3 (summarise segment) must complete across all segments before Node 1 fires.

**Correct execution order:**
```
Phase 1 — Parallel, all segments:
  Node 3  summarise_segment  ×15 segments

Phase 2 — Sequential, depends on Phase 1:
  Node 1  lesson_planner     ← receives segment_summaries[]
  Node 2  slide_generator    ← receives lesson_outline

Phase 1+2 — Parallel with above:
  Node 4  quiz_generator     ×15 segments
  Node 5  segment_complexity ×15 segments
  Node 6  jargon_extractor   ×15 segments
  Node 7  intervention_msgs  ×15 segments
  Node 8  narration_script   ×15 segments

Phase 3 — After all above:
  Node 9  TTS
  Node 10 image_generation
  Node 11 package_builder
```

**Why this matters:** Sending raw chapter text (~12,500 tokens) into the premium lesson planner costs ~5× more than sending clean summaries (~2,500 tokens). Quality also improves because the planner receives structured input instead of dense raw text.

**LangGraph state schema — add this field:**
```python
class PipelineState(TypedDict):
    chapter_text: str
    segments: list[str]
    segment_summaries: list[str]   # ← Node 3 writes, Node 1 reads
    lesson_outline: dict
    slides: list[dict]
    quizzes: list[dict]
    complexities: list[dict]
    jargon: list[dict]
    interventions: list[dict]
    narrations: list[dict]
```

---

### 3. Teach-back is optional — not mandatory after every segment
**Status:** 🔴 BLOCKER  
**PRD reference:** §10 (tutor state machine), §13 (teach-back scorer), §12 (Learner DNA)  
**Affects:** Dev 3 (teach-back scorer, DNA fusion), Dev 4 (state machine)

PRD §10 state machine shows teach-back triggering after every quiz in the `QUIZZING → TEACH-BACK` transition. This is changed to optional.

**Updated state machine transition:**
```
QUIZZING → [show teach-back prompt, student can skip]
         → TEACH-BACK  (if student attempts)
         → TEACHING    (if student skips — no LLM call fires)

TEACH-BACK → TEACHING  (regardless of score — never blocks progress)
```

**Why this matters:**
- Mandatory teach-back on 15 segments = 15 LLM calls per session minimum
- Optional at ~25% attempt rate = ~4 calls per session average
- Saves ~₹28/user/month at scale

**Learner DNA impact:** The DNA fusion formula must handle absent teach-back signals gracefully. Store a confidence score alongside each dimension score:

```python
{
  "cognitive_reasoning_score": 0.72,
  "cognitive_reasoning_confidence": 0.65,  # lower when teach-back was skipped
}
```

Dimensions with low confidence should surface as "still learning about you" in the student profile rather than displaying a potentially inaccurate score.

---

## Architecture Decisions

### 4. Three Railway services — not one
**Status:** 🟡 UPDATED  
**PRD reference:** §27 Decision 1 (Railway as compute host)  
**Affects:** Dev 2 (infrastructure setup)

Running FastAPI backend and ARQ pipeline worker in a single Railway service causes resource contention. A 15-minute PDF processing job consuming CPU and RAM will degrade WebSocket connections for students actively in a session.

**Required service separation:**
```
Service 1: FastAPI backend     (512MB RAM, always-on)
           → handles HTTP, WebSocket, auth, CES, state machine

Service 2: ARQ pipeline worker (1GB RAM, always-on)
           → handles all 11 pipeline nodes, LLM calls, TTS, images

Service 3: Langfuse            (512MB RAM, always-on)
           → self-hosted LLM observability per PRD §19
```

Plus Railway-managed Redis and Supabase (external).

**Monthly cost impact:** ~$82/month total — within PRD §20 target of $60–80/month.

---

### 5. Segmentation is structure-based with a soft token cap
**Status:** 🟡 UPDATED  
**PRD reference:** §9 (segment processing), §20 (cost model — "15-segment chapter")  
**Affects:** Dev 1 (structure detection node, segmentation logic)

PRD §20 uses "15-segment, 50-page PDF" as a planning assumption. The actual segmentation strategy must be structure-based, not fixed page count.

**Segmentation rules:**
```
1. Primary split: at heading/section boundaries from structure detection
2. Soft cap:      if segment > 2,000 tokens → split further at paragraph boundary
3. Soft floor:    if segment < 300 tokens → merge with adjacent segment
4. Store:         segment count in lesson_jobs table for cost tracking
```

The 15-segment figure is a planning average, not a hard constraint. Real chapters will produce 8–25 segments depending on content density and structure. The cost model will be recalibrated once real PDFs are benchmarked.

---

### 6. Chunks table stores vectors only — not raw text
**Status:** 🟢 CONFIRMED  
**PRD reference:** §15 (Supabase schema), §16 (pgvector)  
**Affects:** Dev 1 (database migrations)

Raw extracted chapter text is not stored in the database. It lives in the source PDF in Supabase Storage. The chunks table stores only:

```python
chunks table:
  chunk_id      UUID
  book_id       UUID    # → PDF location in Supabase Storage
  chapter_id    UUID
  chunk_index   int
  page_start    int
  page_end      int
  token_count   int     # for cost tracking
  embedding     vector  # 1536 dimensions (text-embedding-3-small)
```

Raw text is re-extracted on demand via PyMuPDF using `page_start` and `page_end`. Re-extraction takes ~200–300ms — acceptable for Phase 2 RAG tutor queries.

---

### 7. Video delivery — Bunny Stream for reused avatar clips
**Status:** 🟢 CONFIRMED  
**PRD reference:** §6.2 (lesson player), HeyGen avatar  
**Affects:** Dev 2 (infrastructure)

The lesson player uses a fixed reusable avatar clip, not a per-lesson generated video. Architecture is audio + slides in sync, with avatar clip playing at intro/outro only.

```
Avatar clips:    Generated once, stored in Bunny Stream
Audio:           Per-lesson MP3, stored in Supabase Storage
Slides:          JSONB rendered in browser — no video file
Lesson player:   Custom React audio-timeline state machine
```

Bunny Stream at ~$2/month handles 500 users × 15 lesson plays at this scale. No transcoding cost — encode clips once on upload.

---

## Cost Model Decisions That Affect Product Design

### 8. Narration hard cap — 8,000–10,000 characters per lesson
**Status:** 🟡 UPDATED  
**PRD reference:** Node 8 (narration_generator)  
**Affects:** Dev 1 (Node 8 prompt + output validation)

TTS narration is 67–73% of total lesson generation cost. Without a cap, a dense chapter can generate 15,000-char narration costing ₹45 in TTS alone — more than all LLM nodes combined.

**Hard cap:** Node 8 must enforce a maximum output of 10,000 characters per lesson (across all segments combined). The prompt must instruct the model accordingly and output validation must truncate or reject outputs exceeding this limit.

**Expected case:** 8,000 characters (~5 minutes of audio at Sarvam v3 speed).

---

### 9. Chapter generation credits — hard cap per plan
**Status:** 🟡 UPDATED  
**PRD reference:** §13 (credit system)  
**Affects:** Dev 4 (credit deduction logic), product spec

Heavy users (30+ chapters/month) are structurally loss-making on any flat subscription. Credit caps are not optional — they are what makes unit economics viable.

**Recommended tier structure:**

| Tier | Price | Chapter cap | Extra chapter |
|------|-------|-------------|---------------|
| Free | ₹0 | 1 chapter/month | Not available |
| Starter | ₹799 | 10 chapters/month | ₹35/chapter |
| Standard | ₹999 | 20 chapters/month | ₹35/chapter |
| Pro | ₹1,499 | 30 chapters/month | ₹35/chapter |

> Note: These tier prices are provisional pending the benchmark sprint on real PDFs. Do not hardcode them anywhere — use a config table.

**Credit deduction rule (unchanged from PRD):** Deduct 1 credit only on confirmed successful lesson package storage — never on click, never on pipeline start.

---

### 10. Free tier hard limits
**Status:** 🟡 UPDATED  
**PRD reference:** §13  
**Affects:** Dev 4 (credit/entitlement logic)

A free user with no limits can generate 30 chapters costing ₹480 — more than a paying ₹499 subscriber earns you. Free tier must be enforced at the entitlement layer.

**Free tier limits:**
```
Chapter generations:   1 per month
TTS narration:         disabled (text-only lesson)
Teach-back scoring:    disabled
Tutor Q&A:             disabled
Book library cap:       3 books
```

---

## Decisions Explicitly Out of MVP Scope

### 11. Tutor Q&A is Phase 2 only
**Status:** 🟢 CONFIRMED  
**PRD reference:** §11 (tutor state machine — Phase 2)

Current pricing model is valid only without tutor. When Phase 2 RAG tutor launches, pricing must be re-evaluated entirely. Tutor adds ₹8–₹150/user/month depending on question volume (Light 25Q → ₹8, Power 500Q → ₹150).

**Trigger for pricing re-evaluation:** When tutor contributes more than 20% of total AI spend per user.

---

### 12. Institutional pricing is Phase 2 only
**Status:** 🟢 CONFIRMED

Consumer tiers (₹799–₹1,499) must never be applied to coaching institutes or schools. A 200-learner institute at ₹999/learner = ₹1,99,800 revenue but ₹1,15,000 AI cost alone before infrastructure.

Institutional pilots in Phase 2 on cost-plus contracts only. Do not actively sell to institutions in Phase 1.

---

## Still Open — No Decision Yet

These items are unresolved and block pricing finalisation. They will be resolved once the real PDF benchmark sprint is complete.

| Item | Blocker for | Expected resolution |
|------|-------------|---------------------|
| Tokens per page (real PDFs) | Cost model accuracy | PDF benchmark sprint |
| Average narration length (real lessons) | TTS cost model | PDF benchmark sprint |
| Real chapter segment count | Pipeline cost per lesson | PDF benchmark sprint |
| Final model provider selection | Stack A/B validation | After testing sprint |
| Subscription price finalisation | Launch pricing | After 90-day production cohort |
| OCR document mix (% scanned uploads) | OCR cost modeling | After first user cohort |

---

## Verified Provider Prices (as of June 17, 2026)

For reference — these are the locked inputs to the cost model. Do not use cached or old figures.

| Provider | Model | Price |
|----------|-------|-------|
| Google | Gemini 2.5 Flash-Lite | $0.10 in / $0.40 out per MTok |
| OpenAI | GPT-5.4 | $2.50 in / $15.00 out per MTok |
| OpenAI | GPT-5.4 nano | $0.20 in / $1.25 out per MTok |
| Anthropic | Claude Sonnet 4.6 | $3.00 in / $15.00 out per MTok |
| Anthropic | Claude Haiku 4.5 | $1.00 in / $5.00 out per MTok |
| Sarvam AI | Bulbul v3 | ₹30 per 10,000 chars |
| Sarvam AI | Bulbul v2 | ₹15 per 10,000 chars |
| OpenAI | GPT Image 1 Mini | $0.005 per image |
| Google | Imagen 4 Fast (Vertex) | $0.020 per image |
| Bunny Stream | Video delivery | ~$0.01/GB, $1 minimum |
| Batch API | OpenAI + Anthropic | 50% off all async pipeline calls |
| FX rate | USD → INR | ₹95 (June 17, 2026) |

---

*Document prepared June 18, 2026. Supersedes all prior pricing and architecture notes circulated in the team. Next update expected after the PDF benchmark sprint.*
