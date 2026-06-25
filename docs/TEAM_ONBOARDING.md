# TransformED AI — Team Onboarding & BMAD Development Guide

> **Who this is for:** Every developer joining the TransformED AI project.
> **Read time:** ~20 minutes. Read it fully before writing a single line of code.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites — Install These First](#2-prerequisites)
3. [Repository Setup](#3-repository-setup)
4. [Understanding BMAD](#4-understanding-bmad)
5. [Your Role — The 4 Dev Personas](#5-your-role)
6. [The BMAD Workflow for TransformED](#6-bmad-workflow)
7. [How to Use BMAD Skills in Claude Code](#7-using-bmad-skills)
8. [Story Lifecycle — Start to Done](#8-story-lifecycle)
9. [Daily Development Loop](#9-daily-development-loop)
10. [Sprint Ceremonies](#10-sprint-ceremonies)
11. [Project-Specific Slash Commands](#11-project-slash-commands)
12. [Architecture Rules — Must Read](#12-architecture-rules)
13. [Interface Contracts — The Frozen Files](#13-interface-contracts)
14. [Anti-Deadlock Rules](#14-anti-deadlock-rules)
15. [Definition of Done](#15-definition-of-done)
16. [Quick Reference Cheat Sheet](#16-quick-reference)

---

## 1. Project Overview

**TransformED AI** is an adaptive EdTech SaaS platform that converts any uploaded college PDF into a fully interactive AI-taught lesson — complete with slides, narration, avatar, quizzes, teach-back evaluation, and real-time engagement monitoring.

**The single success metric for Phase 1:** One paying student completes a full session without requesting a refund. Everything else is Phase 2.

**10-week build. 4 developers. Zero blocking dependencies after Week 1.**

| Sprint | Weeks | Milestone |
|--------|-------|-----------|
| Sprint 0 | 1 | ✅ Done — infra, shared contracts, monorepo |
| Sprint 1 | 2–3 | Core pipeline + player skeleton |
| Sprint 2 | 4–5 | Full pipeline + integration → investor demo |
| Sprint 3 | 6–7 | MediaPipe + CES + full tutor machine — **prerequisite:** migrate FastAPI/ARQ from Railway to India-region provider before real students join |
| Sprint 4 | 8–9 | Load test + Stripe + hardening |
| Launch | 10 | First paying student |

---

## 2. Prerequisites

Install everything before cloning the repo.

### Required Tools

```bash
# Node.js (v20+)
# Download from https://nodejs.org or use nvm

# pnpm (JS package manager)
npm install -g pnpm

# Python 3.12
# Download from https://python.org

# uv (Python package manager — replaces pip/venv)
pip install uv

# Supabase CLI
npm install -g supabase

# Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Git
# Already installed on most systems
```

### Accounts You Need Access To
Ask the team lead to invite you to:
- [ ] GitHub — `developer-cybersmith/transformED` repo
- [ ] Railway — project access (deploy environments)
- [ ] Supabase — project access (DB + storage)
- [ ] OpenAI — API key
- [ ] Sarvam AI — API key (primary TTS: Bulbul v2)
- [ ] Langfuse — self-hosted instance access
- [ ] Sentry — project access

---

## 3. Repository Setup

```bash
# 1. Clone the repo
git clone https://github.com/developer-cybersmith/transformED.git
cd transformED

# 2. Copy environment file and fill in your keys
cp .env.example .env
# Edit .env with your actual API keys — ask team lead for shared keys

# 3. Install JavaScript dependencies
pnpm install

# 4. Install Python dependencies (API backend)
cd apps/api
uv pip install -e ".[dev]"
cd ../..

# 5. Start Supabase locally
supabase start
# This runs Postgres + Auth + Storage locally on your machine

# 6. Run the first migration
supabase db reset
# This applies supabase/migrations/ to your local DB

# 7. Open the project in Claude Code
claude  # opens in the current directory
```

### Verify the setup

```bash
# Backend runs
cd apps/api && uvicorn app.main:app --reload
# Should start on http://localhost:8000
# Visit http://localhost:8000/health → {"status": "ok"}

# Frontend runs
cd apps/web && pnpm dev
# Should start on http://localhost:3000
```

---

## 4. Understanding BMAD

**BMAD (Breakthrough Method of Agile AI-driven Development)** is the development framework we use to work with Claude Code efficiently as a team.

### Core idea

Instead of just asking Claude to "write some code", BMAD gives Claude a **structured role** (analyst, architect, developer, QA) and a **structured workflow** (story → tasks → implementation → review). This means:

- Claude knows *what phase* it's in and *what to produce*
- Every developer works from the same story format
- AI-generated code is traceable back to a story and acceptance criteria
- No context is lost between sessions

### BMAD is installed in this project at:

```
.claude/skills/         ← 44 BMAD skills (slash commands in Claude Code)
_bmad/                  ← BMAD core + BMM module configuration
_bmad-output/           ← Where BMAD writes planning + implementation artifacts
docs/bmad/epics/        ← 5 TransformED epics (source of all stories)
```

### The BMM Workflow Phases

BMAD uses the **BMM (BMAD Method Module)** which has 4 phases:

```
Phase 1: Analysis     → Understand requirements (PRD is our input — already done ✅)
Phase 2: Plan         → Epics + stories (partially done ✅, continuing in Sprint 1)
Phase 3: Solutioning  → Architecture decisions (done ✅ — see CLAUDE.md)
Phase 4: Implementation → Build stories (THIS IS WHERE WE ARE NOW)
```

**You are joining at Phase 4.** Your job is to implement stories.

### Where output goes

| Type | Location |
|------|----------|
| Planning artifacts (epics, PRD analysis) | `_bmad-output/planning-artifacts/` |
| Implementation artifacts (stories, specs) | `_bmad-output/implementation-artifacts/` |
| Epics | `docs/bmad/epics/` |
| Stories | `_bmad-output/implementation-artifacts/stories/` (created by BMAD) |

---

## 5. Your Role

There are **4 developer roles**. Each role has a specific ownership area and a BMAD agent persona. Know which one you are — it determines which stories you pick up and which files you touch.

### Dev 1 — Infrastructure + Content Pipeline

**BMAD persona:** `/bmad-agent-dev` (focus: backend pipeline)

**You own:**
- All 11 content pipeline nodes (`apps/api/app/modules/content/pipeline/nodes/`)
- PDF ingestion (PyMuPDF + pdfplumber + Tesseract)
- Embedding generation + pgvector storage
- Provider abstraction layer (`apps/api/app/providers/`)
- ARQ workers (`apps/api/app/workers/`)
- `lesson_jobs` checkpointing + crash recovery
- `with_retry()` + circuit breaker (`apps/api/app/core/`)
- Langfuse observability + eval harness
- Supabase migrations, Railway config, CI/CD

**Your epic:** `docs/bmad/epics/epic-1-content-pipeline.md`

---

### Dev 2 — Frontend + Lesson Player

**BMAD persona:** `/bmad-agent-dev` (focus: React/Next.js)

**You own:**
- Custom audio-timeline player (`apps/web/src/features/player/`)
- MediaPipe attention capture (`apps/web/src/features/attention/`)
- Quiz + teach-back UI (`apps/web/src/features/quiz/`, `teachback/`)
- Tutor intervention cards (`apps/web/src/features/tutor/`)
- All Next.js routes (`apps/web/src/app/`)
- Dashboard, upload page, onboarding UI
- WebSocket client (`apps/web/src/lib/websocket/`)
- PostHog analytics

**Your epic:** `docs/bmad/epics/epic-2-lesson-player.md`

---

### Dev 3 — Assessment + Analytics + Learner DNA

**BMAD persona:** `/bmad-agent-dev` (focus: scoring + analytics)

**You own:**
- Quiz API + MCQ scoring (`apps/api/app/modules/assessment/`)
- Teach-back scorer (GPT-4o-mini rubric)
- Session report API
- CES formula implementation
- Learner DNA onboarding assessment + fusion algorithm
- Learner DNA profile generation
- Analytics module (`apps/api/app/modules/analytics/`)
- PostHog event instrumentation

**Your epic:** `docs/bmad/epics/epic-3-assessment-dna.md`

---

### Dev 4 — Tutor Agent + CES + Realtime

**BMAD persona:** `/bmad-agent-dev` (focus: realtime + state machines)

**You own:**
- JWT middleware (`apps/api/app/dependencies.py`)
- WebSocket handlers + connection manager (`apps/api/app/core/websocket.py`)
- 7-state LangGraph tutor machine (`apps/api/app/modules/tutor/state_machine/`)
- CES computation engine (Redis-buffered, in-process)
- Intervention trigger logic + guard rules
- Session state persistence (Redis 24h TTL)
- Attention ingestion pipeline
- Sentry error monitoring

**Your epic:** `docs/bmad/epics/epic-4-tutor-ces.md`

---

## 6. BMAD Workflow

Here is the full flow for how a story gets from the PRD to merged code:

```
PRD (source of truth)
    │
    ▼
Epic documents (docs/bmad/epics/epic-X-*.md)
    │  Created by: /bmad-agent-pm or /bmad-create-epics-and-stories
    ▼
Story files (_bmad-output/implementation-artifacts/stories/S*.md)
    │  Created by: /bmad-create-story
    ▼
Story implementation (code in apps/)
    │  Driven by: /bmad-dev-story
    ▼
Code review
    │  Run by: /bmad-code-review
    ▼
Merged to main
```

### Who creates stories?

The **PM agent** (`/bmad-agent-pm`) or **Scrum Master** creates stories from epics at the start of each sprint. Once created, each dev picks up their assigned stories and implements them.

If you need a story created for a new piece of work:
```
/bmad-create-story
```

---

## 7. Using BMAD Skills in Claude Code

### Opening Claude Code

```bash
cd /path/to/transformED
claude
```

Claude Code will automatically load:
- `CLAUDE.md` — project rules and architecture constraints
- All 44 BMAD skills from `.claude/skills/`
- All 6 project-specific commands from `.claude/commands/`

### Key BMAD commands

Type these directly in the Claude Code prompt:

| Command | When to use |
|---------|------------|
| `/bmad-help` | Not sure what to do next — always start here |
| `/bmad-agent-dev` | Activate developer agent to implement a story |
| `/bmad-agent-pm` | Activate PM agent (John) for story creation / backlog work |
| `/bmad-agent-analyst` | Activate analyst agent (Mary) for requirement questions |
| `/bmad-agent-architect` | Activate architect agent (Winston) for architecture decisions |
| `/bmad-dev-story` | Implement a specific story file end-to-end |
| `/bmad-create-story` | Create a new story file from an epic |
| `/bmad-sprint-planning` | Generate sprint status from epics |
| `/bmad-sprint-status` | Check current sprint progress |
| `/bmad-code-review` | Run adversarial code review on your changes |
| `/bmad-check-implementation-readiness` | Validate a story is ready to implement |
| `/bmad-retrospective` | Run sprint retrospective |
| `/bmad-correct-course` | Manage a mid-sprint scope change |

### Project-specific commands (TransformED only)

| Command | When to use |
|---------|------------|
| `/new-feature <name>` | Scaffold a new feature (frontend + backend) |
| `/gen-prompt <module> <name> <model>` | Create a versioned LLM prompt file |
| `/add-pipeline-node <name> <criticality>` | Add a node to the LangGraph pipeline |
| `/add-migration <description>` | Create a new Supabase migration |
| `/run-evals` | Run lesson quality eval harness |
| `/check-costs` | Report AI spend vs $3.00/lesson ceiling |

---

## 8. Story Lifecycle

### Step 1: Find your story

Stories for the current sprint are in `_bmad-output/implementation-artifacts/stories/`.
Each story file is named like `S1-D1-001-pdf-upload.md` (Sprint 1, Dev 1, Story 001).

Pick a story with `status: todo` that matches your dev role (D1/D2/D3/D4).

### Step 2: Read the story fully

Every story has:
- **User story** — the "as a X, I want Y" framing
- **Acceptance criteria** — the checkboxes you must satisfy
- **Technical notes** — implementation guidance
- **Tasks** — step-by-step breakdown
- **Definition of Done** — your exit gate

Don't start coding until you understand all acceptance criteria.

### Step 3: Implement using BMAD

```
/bmad-dev-story
```

Then tell Claude: "I'm working on story `S1-D1-001`. The file is at `_bmad-output/implementation-artifacts/stories/S1-D1-001-pdf-upload.md`."

Claude will:
1. Read the story file
2. Check what's already done
3. Implement each task sequentially
4. Update the story file's checkboxes as it goes
5. Never stop mid-story unless it hits a blocker

### Step 4: Self-review

Before pushing, run:
```
/bmad-code-review
```

This runs a 3-layer adversarial review: Blind Hunter (correctness) + Edge Case Hunter + Acceptance Auditor (checks against story ACs).

### Step 5: Update story status

In the story file's YAML frontmatter:
```yaml
status: done  # was: in_progress
```

### Step 6: Create PR

```bash
git checkout -b feat/S1-D1-001-pdf-upload
git add -A
git commit -m "feat(content): implement PDF upload + ARQ job enqueue (S1-D1-001)"
git push origin feat/S1-D1-001-pdf-upload
# Create PR on GitHub
```

---

## 9. Daily Development Loop

```
Morning:
  1. git pull origin main
  2. Open Claude Code: claude
  3. /bmad-sprint-status  ← see what's in progress
  4. Pick up your next story or continue yesterday's

During the day:
  5. /bmad-dev-story  ← implement your story
  6. Write tests alongside code
  7. /bmad-code-review  ← before pushing anything

End of day:
  8. Push your branch (even if incomplete — WIP commits are fine)
  9. Update the story status in the story file
  10. Note any blockers as a comment in the story file
```

### If you're blocked

If you're blocked on another dev's interface:
- **Don't wait.** Mock it. Every dev has a contract they own (see §13).
- Use the mock/stub pattern in your tests.
- Leave a `TODO(S1-D4-001): replace with real WebSocket once wired` comment.
- Flag the blocker in the story file's Dev Agent Record.

---

## 10. Sprint Ceremonies

### Sprint Planning (Start of sprint, ~2 hours)

```
/bmad-agent-pm   ← activate PM agent
```
Then: "Run sprint planning for Sprint [N]. The epics are in `docs/bmad/epics/`."

Output: sprint story files created, sprint status YAML generated.

### Daily Standup (15 min, async-friendly)

Post in the team channel:
```
✅ Yesterday: [what story you completed / progressed]
🔨 Today: [story ID you're working on]
🚧 Blockers: [any blockers or dependencies needed]
💰 Cost note: [if you ran evals, what was the per-lesson cost]
```

### Mid-Sprint AI Review (Day 7, 30 min)

```
/bmad-sprint-status
/run-evals --all   ← check lesson quality
/check-costs       ← verify within $3.00 ceiling
```

### Sprint Review (End of sprint, 1 hour)

Demo working features. Show actual lesson output. Review eval scores vs baseline.

### Retrospective (End of sprint, 45 min)

```
/bmad-retrospective
```

Specific AI retro questions:
- Did any prompt changes cause quality regressions?
- What was the average cost per lesson?
- Did any intervention fire correctly in test sessions?
- What's our P95 pipeline latency?

---

## 11. Project Slash Commands

These are TransformED-specific commands (not generic BMAD). They enforce project patterns automatically.

### `/new-feature <name>`

Creates a feature scaffold in both frontend and backend:
```
apps/web/src/features/<name>/
  index.ts          ← public exports
  <Name>.tsx        ← main component
  use<Name>.ts      ← data hook
  <name>.test.ts    ← co-located tests

apps/api/app/modules/<name>/
  __init__.py
  router.py         ← FastAPI router
  service.py        ← business logic
  schemas.py        ← Pydantic models
```

### `/gen-prompt <module> <name> <model>`

Creates a versioned prompt file:
```python
# apps/api/app/modules/<module>/prompts/<name>.py
PROMPT_VERSION = "v1.0.0"   # bump on every change

SYSTEM = """..."""

def build_user_message(*, typed_inputs) -> str:
    return f"..."
```

**Never hardcode prompts inline in service files. Always use this pattern.**

### `/add-pipeline-node <name> <criticality>`

Adds a new LangGraph pipeline node with:
- `@with_retry(max_attempts=3)` for critical, `max_attempts=2` for optional
- Correct position in the pipeline graph
- Progress percentage update
- Checkpoint write to `lesson_jobs`

### `/add-migration <description>`

Creates `supabase/migrations/<timestamp>_<description>.sql` with the correct template including RLS policies and indexes. **Never manually edit an already-applied migration.**

### `/run-evals`

Runs the lesson quality evaluation harness against test PDFs. Week 5 gate: 15/20 PDFs must be rated "useful to a student."

### `/check-costs`

Queries Langfuse to report per-lesson AI spend. Hard ceiling: **$3.00/lesson**. Flag to the team immediately if any lesson exceeds $2.50.

---

## 12. Architecture Rules

> **These are hard rules, not guidelines. PRs that violate them will be rejected.**

### Banned libraries / approaches

| What | Why it's banned | What to use instead |
|------|-----------------|---------------------|
| **Celery** | Wrong model for async I/O | **ARQ** |
| **PostgresSaver** (LangGraph) | Conflicts with Supabase PgBouncer + asyncpg | Custom `lesson_jobs` table + **MemorySaver** |
| **Reveal.js** | Click model can't do timeline sync | Custom React audio-timeline state machine |
| **WebGazer** | Single-signal, ~4° error, unmaintained | **MediaPipe Face Landmarker** (WASM) |
| **Azure Document Intelligence** | Cross-cloud latency, cost | **Tesseract** (in-container) |
| **Kimi / Qwen** | China-hosted, DPDP Act data residency risk | OpenAI / Claude |
| **Direct provider API calls in business logic** | Violates provider abstraction | Use `app/providers/` classes |
| **Regenerating stored chunk embeddings** | Cost + latency; stored embeddings are immutable | Embed chunks at ingestion only. **Exception:** Phase 2 RAG tutor embeds the student's *question* at query time — this is permitted and required. |
| **Microservices** | Premature ops tax | Modular monolith |
| **IQ / EQ / SQ terminology** | Legal and credibility liability | "Learner DNA" branding only |
| **Raw dimension scores shown to students** | Legal risk | Descriptive profile only |
| **Teach-back timer** | Creates test anxiety, explicit PRD rule | No timer ever |
| **Gating lesson progress on teach-back score** | Churns users before calibration data exists | Always allow "Continue" |
| **STT / microphone** | Complexity + voice consent surface | Typed teach-back only |
| **LangGraph auto-upgrade** | Version changes break pipeline silently | Pin exact version |

### Pipeline execution order (third most violated rule)

Phase B.1 economy nodes (`summarise_segment`, `quiz_generator`, `segment_complexity`, `jargon_extractor`, `intervention_msgs`, `narration_script`) run **in parallel** across all segments FIRST. Only after **all** Phase B.1 nodes complete does Phase B.2 start.

`lesson_planner` receives segment **summaries** as input — never raw chapter text. Violating this silently causes a 5× cost overrun.

### The One Discipline Rule (most violated rule)

Modules communicate **only through their service layer**. Never reach into another module's DB tables directly.

```python
# ✅ CORRECT
from app.modules.assessment.service import get_quiz_score

# ❌ WRONG — never do this
from app.core.db import get_supabase
supabase.table("quiz_attempts").select("*")...  # from inside the tutor module
```

### Provider abstraction (second most violated rule)

```python
# ✅ CORRECT — in any node or service
from app.providers.llm.openai import OpenAILLMProvider
result = await OpenAILLMProvider(lesson_id).complete(messages, model)

# ❌ WRONG — direct client call
from openai import AsyncOpenAI
client = AsyncOpenAI()
result = await client.chat.completions.create(...)
```

### Cost ceiling enforcement

Every provider call must go through `cost_tracker.accumulate_cost(lesson_id, cost)`. If `cost_tracker.check_ceiling(lesson_id)` returns `True`, raise `CostLimitExceeded` — don't silently skip.

---

## 13. Interface Contracts

These 4 files are **frozen**. Any change requires a PR reviewed by all 4 developers before merging.

| Contract | File | Owner |
|----------|------|-------|
| Lesson Package schema | `packages/shared/lesson_package.schema.json` | Dev 1 |
| TypeScript lesson types | `packages/shared/types/lesson.ts` | Dev 1 |
| WebSocket message types | `packages/shared/types/ws.ts` | Dev 4 |
| DB migrations | `supabase/migrations/` (never edit applied) | Dev 1 |

Two migrations are applied and frozen (do NOT alter):
- `20260611000000_initial_schema.sql` — initial schema
- `20260625000000_chunks_inline_embedding.sql` — books table, inline embedding, lessons.book_id (applied 2026-06-25)

If you need to change a contract:
1. Open a discussion in the team channel first
2. Get sign-off from all 4 devs
3. Create a PR specifically for the contract change
4. Update Pydantic schemas in Python to match TypeScript types

---

## 14. Anti-Deadlock Rules

Sprint 0 froze the contracts. This means **you never wait on another dev**:

| If you need | Mock it with |
|-------------|-------------|
| WebSocket messages | `packages/shared/types/ws.ts` — use the discriminated union |
| Lesson package data | `packages/shared/types/lesson.ts` — create a fixture |
| Assessment API | The OpenAPI spec (auto-generated from FastAPI) |
| DB schema | The migration file — run `supabase db reset` locally |

**The anti-deadlock mantra:** *"If it's in the contract, I can build against it today."*

Leave `TODO` comments where integration will happen, then remove them at sprint integration day (last day of each sprint).

---

## 15. Definition of Done

A story is **not done** until every box is checked:

### Code quality
- [ ] All acceptance criteria from the story file are satisfied
- [ ] `ruff check .` passes with zero errors
- [ ] `mypy app` passes (or `pnpm type-check` for frontend)
- [ ] Unit tests written and passing (`pytest tests/unit` / `pnpm test`)
- [ ] No `any` types in TypeScript without a comment explaining why
- [ ] No direct provider calls in business logic

### AI-specific (if story touches LLM/TTS/Image)
- [ ] Prompt file created with `PROMPT_VERSION = "v1.0.0"` in `modules/<name>/prompts/`
- [ ] Cost per call estimated and within budget
- [ ] `cost_tracker.accumulate_cost()` called after every provider call
- [ ] `@with_retry(max_attempts=3)` on critical nodes, `max_attempts=2` on optional

### Architecture
- [ ] No module reaches into another module's DB tables
- [ ] All AI calls go through `app/providers/` not direct client calls
- [ ] No banned library used

### Security
- [ ] All new DB tables have RLS enabled
- [ ] No secrets in code (use `settings.*` from config)
- [ ] User input validated at the endpoint (never trust client data)

### PR
- [ ] Branch named `feat/S<n>-D<n>-<nnn>-<slug>`
- [ ] Commit message references story ID: `feat(module): description (S1-D1-001)`
- [ ] Story file `status` updated to `done`
- [ ] PR description links to story file

---

## 16. Quick Reference Cheat Sheet

```
┌─────────────────────────────────────────────────────────────────────┐
│  TRANSFORMEDED AI — BMAD QUICK REFERENCE                            │
├─────────────────────────────────────────────────────────────────────┤
│  START OF DAY                                                        │
│    git pull origin main                                              │
│    claude                          ← open Claude Code               │
│    /bmad-sprint-status             ← what's in progress?            │
│    /bmad-dev-story                 ← implement your story           │
├─────────────────────────────────────────────────────────────────────┤
│  NEED HELP?                                                          │
│    /bmad-help                      ← always start here              │
│    /bmad-agent-analyst             ← PRD/requirement questions       │
│    /bmad-agent-architect           ← architecture decisions          │
│    /bmad-agent-pm                  ← story creation / backlog        │
├─────────────────────────────────────────────────────────────────────┤
│  CREATING THINGS                                                     │
│    /bmad-create-story              ← new story from epic             │
│    /new-feature <name>             ← scaffold frontend + backend     │
│    /gen-prompt <mod> <name> <mdl>  ← versioned LLM prompt           │
│    /add-pipeline-node <n> <crit>   ← new LangGraph node             │
│    /add-migration <description>    ← new DB migration                │
├─────────────────────────────────────────────────────────────────────┤
│  REVIEWING                                                           │
│    /bmad-code-review               ← before every PR                 │
│    /run-evals --all                ← lesson quality check            │
│    /check-costs                    ← AI spend vs $3.00 ceiling       │
├─────────────────────────────────────────────────────────────────────┤
│  BANNED (instant PR rejection)                                       │
│    Celery / PostgresSaver / Reveal.js / WebGazer                    │
│    Direct openai.client calls in business logic                      │
│    Reaching into another module's DB tables                          │
│    IQ/EQ/SQ terminology / raw dimension scores                       │
│    Teach-back timer / gating lesson progress on score                │
├─────────────────────────────────────────────────────────────────────┤
│  KEY PATHS                                                           │
│    Backend:     apps/api/app/                                        │
│    Frontend:    apps/web/src/                                        │
│    Shared:      packages/shared/types/  ← FROZEN contracts           │
│    Migrations:  supabase/migrations/    ← never edit applied         │
│    Epics:       docs/bmad/epics/                                     │
│    Stories:     _bmad-output/implementation-artifacts/stories/       │
│    Your rules:  CLAUDE.md                                            │
├─────────────────────────────────────────────────────────────────────┤
│  COST LIMITS                                                         │
│    Per lesson: $3.00 hard ceiling (flag at $2.50)                   │
│    Per user/day: $10.00                                              │
│    Infra/month: $60-80                                               │
├─────────────────────────────────────────────────────────────────────┤
│  MODELS (never hardcode — use settings.*)                            │
│    Lesson planning, slides: GPT-4o  (settings.llm_lesson_planner)   │
│    Quiz, scoring, narration: GPT-4o-mini  (settings.llm_mini)       │
│    Tutor Q&A (Phase 2): GPT-4o  (settings.llm_tutor)               │
│    Model eval sprint: Sprint 1 Wk 1 — defaults above until locked   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Appendix: File Structure Reference

```
transformED-corp/
├── CLAUDE.md                    ← READ THIS. Project rules for Claude Code.
├── .env.example                 ← Copy to .env, fill in keys
├── .gitignore                   ← Monorepo-wide ignores
│
├── .claude/
│   ├── settings.json            ← Permissions (auto-allowed tools)
│   ├── skills/                  ← 44 BMAD skills (auto-loaded)
│   └── commands/                ← 6 project-specific slash commands
│
├── _bmad/                       ← BMAD framework files (don't edit)
│   ├── bmm/                     ← BMM module (1-analysis → 4-implementation)
│   └── config.toml              ← BMAD config (project name, output dirs)
│
├── _bmad-output/
│   ├── planning-artifacts/      ← Epics, PRD analysis output
│   └── implementation-artifacts/
│       └── stories/             ← Story files (S1-D1-001.md etc.)
│
├── apps/
│   ├── api/                     ← FastAPI backend (Python 3.12)
│   │   ├── app/
│   │   │   ├── main.py          ← App factory
│   │   │   ├── config.py        ← All env vars (settings.*)
│   │   │   ├── dependencies.py  ← JWT verify, Redis, settings deps
│   │   │   ├── modules/         ← auth|content|media|assessment|analytics|tutor|admin
│   │   │   │   └── content/pipeline/nodes/  ← 11 LangGraph nodes
│   │   │   ├── providers/       ← LLM|TTS|Image|Avatar abstractions
│   │   │   ├── core/            ← db|redis|retry|circuit_breaker|cost_tracker|websocket
│   │   │   └── workers/         ← ARQ entry + content_pipeline job
│   │   ├── pyproject.toml       ← Python deps + tool config
│   │   └── Dockerfile
│   │
│   └── web/                     ← Next.js 14 (TypeScript + Tailwind)
│       └── src/
│           ├── app/             ← App Router routes
│           ├── features/        ← player|attention|quiz|teachback|tutor|onboarding
│           ├── lib/             ← supabase|websocket|api clients
│           └── components/ui/
│
├── packages/
│   └── shared/                  ← FROZEN — shared contracts
│       ├── types/lesson.ts      ← LessonPackage TypeScript types
│       ├── types/ws.ts          ← WebSocket discriminated union
│       └── lesson_package.schema.json
│
├── supabase/
│   ├── config.toml              ← Local Supabase config
│   └── migrations/              ← DB schema (never edit applied migrations)
│
├── docs/
│   ├── TEAM_ONBOARDING.md       ← This file
│   ├── agile-process.md         ← AI-agile process definition
│   ├── adr/                     ← Architecture Decision Records
│   └── bmad/
│       └── epics/               ← 5 TransformED epic documents
│
└── .github/workflows/
    ├── ci.yml                   ← Lint + test on every PR
    └── deploy.yml               ← Deploy to Railway on main push
```

---

*Questions? Ping the team channel first. If it's an architecture question, invoke `/bmad-agent-architect`. If it's a requirements question, invoke `/bmad-agent-analyst`. If you're not sure, `/bmad-help`.*
