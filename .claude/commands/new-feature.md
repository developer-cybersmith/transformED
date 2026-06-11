# /new-feature

Creates the standard file scaffolding for a new feature in the transformED platform.

## Usage
`/new-feature <feature-name>`

## What it does
1. Creates the feature directory under the appropriate app
2. Scaffolds component, hook, API route, and test files
3. Adds the feature to the route manifest if applicable

## Template
When invoked, create the following structure for `<feature-name>`:
- `apps/web/src/features/<feature-name>/index.ts` — public exports
- `apps/web/src/features/<feature-name>/<FeatureName>.tsx` — main component
- `apps/web/src/features/<feature-name>/use<FeatureName>.ts` — data hook
- `apps/web/src/features/<feature-name>/<feature-name>.test.ts` — unit tests
- `apps/api/routers/<feature-name>.py` — FastAPI router (if AI/backend feature)
