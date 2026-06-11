# /gen-prompt

Generate a versioned LLM prompt for a TransformED pipeline node or feature.

## Usage
`/gen-prompt <module-name> <prompt-name> <model>`

Example: `/gen-prompt assessment teachback-scorer gpt-4o-mini`

## What it creates

File: `apps/api/app/modules/<module-name>/prompts/<prompt-name>.py`

```python
# Version this file with semantic versioning.
# Increment minor for prompt wording changes, major for schema/output changes.
PROMPT_VERSION = "v1.0.0"

SYSTEM = """..."""

def build_user_message(*, <typed_inputs>) -> str:
    return f"""..."""
```

## Rules
- Prompts live INSIDE the module that owns them (`modules/<name>/prompts/`)
- Every prompt file has a `PROMPT_VERSION` constant — bump it on any change
- System prompt in a module-level `SYSTEM` constant
- User message built by a typed `build_user_message()` function — never string-interpolated inline
- Model is NOT hardcoded in the prompt file — it comes from `settings.llm_*` env vars
- Add a docstring with: purpose, expected input, expected output format, and cost estimate per call
- For structured outputs (JSON): include the expected JSON schema in the system prompt

## Per-task model reference (PRD §6.4)
| Task | Model setting |
|------|--------------|
| Lesson planning, slide generation | `settings.llm_lesson_planner` (gpt-4o) |
| Quiz, scoring, complexity, narration, jargon, interventions, Learner DNA | `settings.llm_mini` (gpt-4o-mini) |
| Tutor Q&A (Phase 2) | `settings.llm_lesson_planner` or Claude Sonnet |
