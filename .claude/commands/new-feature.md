# /new-feature

Scaffold a new feature across the HIE monorepo.

## Usage
`/new-feature <feature-name>`

Example: `/new-feature lesson-bookmarks`

## What it creates

### Frontend â€” `apps/web/src/features/<feature-name>/`
- `index.ts` â€” public re-exports only
- `<FeatureName>.tsx` â€” main React component
- `use<FeatureName>.ts` â€” data fetching + state hook
- `<feature-name>.test.ts` â€” unit tests (co-located)

### Backend â€” `apps/api/app/modules/<feature-name>/`
- `__init__.py`
- `router.py` â€” FastAPI APIRouter, registered in `apps/api/app/main.py`
- `service.py` â€” business logic; never touches another module's DB tables directly
- `schemas.py` â€” Pydantic request/response models

## Rules
- Module communicates with other modules ONLY through their service layer (PRD Principle 4)
- No direct LLM/TTS/image calls in service.py â€” go through `app/providers/`
- Add the router to `apps/api/app/main.py` under the correct `/api/<name>` prefix
- If the feature needs AI: create a prompt file in `apps/api/app/modules/<feature-name>/prompts.py`

