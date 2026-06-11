# transformED — Claude Code Project Guide

## Project Overview
**transformED** is an AI-powered EdTech SaaS platform. It delivers personalized learning experiences, AI-driven assessments, adaptive content delivery, and analytics for organizations and learners.

## Architecture (TBD — fill in as stack is decided)
- **Frontend**: (e.g. Next.js 14 + TypeScript)
- **Backend / AI layer**: (e.g. FastAPI + LangGraph)
- **Database**: (e.g. Supabase / Postgres)
- **Auth**: (e.g. Supabase Auth / NextAuth)
- **AI models**: Claude (Anthropic) — primary LLM for tutoring, assessment, content generation
- **Vector store**: (e.g. Qdrant / pgvector) — for RAG pipelines

## Repo Structure (target layout)
```
transformED-corp/
├── apps/
│   ├── web/          # Next.js frontend
│   └── api/          # FastAPI AI backend (optional)
├── packages/
│   ├── ui/           # Shared component library
│   ├── ai/           # LLM wrappers, prompts, chains
│   └── db/           # DB schema, migrations, seed
├── docs/             # ADRs, specs, design docs
├── .claude/          # Claude Code project config
└── CLAUDE.md         # This file
```

## Development Principles
- **No premature abstraction** — three similar lines > a helper. Abstract only when 3rd duplication lands.
- **No speculative features** — build exactly what the current sprint story requires.
- **Secure by default** — validate all user input at system boundaries; never trust client-supplied IDs without auth check.
- **AI outputs are untrusted** — always sanitize/validate LLM responses before rendering or persisting.
- **Fail loudly in dev, fail gracefully in prod** — throw in dev, return user-friendly errors in prod.

## Code Style
- TypeScript strict mode everywhere.
- Python: ruff for lint/format, mypy for types.
- No `any` in TypeScript without a comment explaining why.
- Named exports preferred over default exports.
- Co-locate tests next to source (`foo.test.ts` beside `foo.ts`).

## AI / LLM Guidelines
- Use `claude-sonnet-4-6` as the default model for most tasks (speed + quality balance).
- Use `claude-opus-4-8` only for complex multi-step reasoning tasks (cost-aware).
- Use `claude-haiku-4-5-20251001` for high-throughput, low-latency tasks (grading hints, short completions).
- All prompts live in `packages/ai/prompts/` — never inline prompts in business logic.
- Log all LLM inputs/outputs in dev for observability.
- Implement prompt versioning — tag every prompt with a version string.

## Environment Variables
Document all required env vars in `.env.example`. Never commit real secrets.

## Git Workflow
- Branch naming: `feat/`, `fix/`, `chore/`, `docs/`
- Commit style: conventional commits (`feat: add quiz generation endpoint`)
- PRs require passing CI before merge
- Main branch is protected

## Sprint Ceremonies (Agile AI)
See `docs/agile-process.md` for the full process definition.
