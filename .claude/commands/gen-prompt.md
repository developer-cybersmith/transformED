# /gen-prompt

Generates a versioned, structured LLM prompt file for a new AI feature.

## Usage
`/gen-prompt <prompt-name> <purpose>`

## What it does
Creates `packages/ai/prompts/<prompt-name>.ts` with:
- A versioned prompt constant (`PROMPT_VERSION = "v1.0.0"`)
- System and user message templates with typed variables
- JSDoc describing the purpose, inputs, and expected output format
- An example usage comment

## Template structure
```ts
export const PROMPT_VERSION = "v1.0.0";

export const <promptName>Prompt = {
  system: `...`,
  user: (vars: { /* typed inputs */ }) => `...`,
};
```
