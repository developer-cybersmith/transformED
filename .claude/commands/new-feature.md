# /new-feature

Scaffold a new feature across the TransformED monorepo.

## Usage
`/new-feature <feature-name>`

Example: `/new-feature lesson-bookmarks`

## What it creates

### Frontend — `apps/web/src/features/<feature-name>/`
- `index.ts` — public re-exports only
- `<FeatureName>.tsx` — main React component
- `use<FeatureName>.ts` — data fetching + state hook
- `<feature-name>.test.ts` — unit tests (co-located)

### Backend — `apps/api/app/modules/<feature-name>/`
- `__init__.py`
- `router.py` — FastAPI APIRouter, registered in `apps/api/app/main.py`
- `service.py` — business logic; never touches another module's DB tables directly
- `schemas.py` — Pydantic request/response models

## Rules
- Module communicates with other modules ONLY through their service layer (PRD Principle 4)
- No direct LLM/TTS/image calls in service.py — go through `app/providers/`
- Add the router to `apps/api/app/main.py` under the correct `/api/<name>` prefix
- If the feature needs AI: create a prompt file in `apps/api/app/modules/<feature-name>/prompts.py`
