# /check-costs

Report current AI costs from Langfuse and check against the $3.00/lesson ceiling.

## Usage
`/check-costs [--lesson <lesson-id>] [--today] [--user <user-id>]`

## What it does
Queries Langfuse API and the `lesson_jobs` table to report:
- Average cost per lesson (last 7 days)
- Cost breakdown by pipeline node
- Any lessons that hit the $3.00 ceiling
- Daily spend per user (flag anyone near $10.00 limit)
- Most expensive nodes (candidates for model downgrade)

## Cost limits (from .env / PRD §14)
- `MAX_LESSON_COST_USD` = $3.00 hard ceiling per lesson
- `MAX_DAILY_SPEND_PER_USER_USD` = $10.00 per user per day

## Reference — expected costs (PRD §20)
| Item | Target |
|------|--------|
| GPT-4o (slides + planning) | $0.40–0.60 |
| GPT-4o-mini (quiz, scoring, etc.) | $0.03–0.05 |
| ElevenLabs TTS | $0.20–0.40 |
| DALL-E 3 | ~$0.60 |
| **Total typical lesson** | **$1.20–1.65** |

If any node is routinely over budget, suggest downgrading to the mini model or enabling the fallback chain.
