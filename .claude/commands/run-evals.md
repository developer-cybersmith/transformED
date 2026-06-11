# /run-evals

Run the lesson quality evaluation harness against a set of test PDFs.

## Usage
`/run-evals [--pdf <path>] [--all] [--node <node-name>]`

Examples:
- `/run-evals --all` — run all 20 eval PDFs
- `/run-evals --pdf tests/fixtures/sample_chapter.pdf` — run single PDF
- `/run-evals --node slide_generator` — eval only one pipeline node

## What it does
1. Loads test PDFs from `apps/api/tests/fixtures/eval_pdfs/`
2. Runs the full content pipeline (or specified node)
3. Scores output against golden examples in `apps/api/tests/evals/golden/`
4. Reports: lesson quality score, cost per lesson, latency, node-level pass/fail
5. Writes results to `apps/api/tests/evals/results/<timestamp>.json`
6. Logs to Langfuse with eval tag

## Eval criteria (PRD Week 5 Gate)
- 15 of 20 PDFs rated "useful to a student" by human reviewer
- Zero user-visible stack traces
- No lesson stuck in "generating" forever
- Cost per lesson ≤ $3.00

## Files
- Golden examples: `apps/api/tests/evals/golden/<pdf-name>/`
- Eval runner: `apps/api/tests/evals/runner.py`
- Fixtures: `apps/api/tests/fixtures/eval_pdfs/` (add real college PDFs here)

## Running manually
```bash
cd apps/api
pytest tests/evals/ -v --tb=short
```
