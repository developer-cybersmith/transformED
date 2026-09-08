# Learner DNA Profile Quality Checklist (Story 4-33)

**Reviewer:** Dev 3 (tannmayygupta)
**Date:** 2026-09-05
**Status:** Template — complete with real profiles when ≥ 10 student profiles exist.

---

## Automated Check

Run before this human review:
```bash
SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/dna_profile_quality_check.py
```
All 5 automated criteria must PASS before the human review begins.

---

## Human Review Checklist (10 profiles)

For each profile, score 1–5 on each dimension (5 = excellent, 1 = needs rewrite).
Flag any profile scoring < 3 on any dimension.

### Review Criteria

| # | Criterion | What to check |
|---|-----------|---------------|
| A | Encouraging tone | Does the text feel motivating, not judgmental? No deficit language. |
| B | Plain English | No jargon, no clinical terms, no acronyms. |
| C | Specificity | Does it describe THIS student's pattern, not a generic archetype? |
| D | Grammar + spelling | No errors, no run-on sentences, 2–3 clear sentences. |
| E | DPDP disclaimer present | Visible at end of the profile text shown to student. |

### Score Table

| Profile # | User (anon) | A | B | C | D | E | Flag? |
|-----------|-------------|---|---|---|---|---|-------|
| 1  | — | — | — | — | — | — | — |
| 2  | — | — | — | — | — | — | — |
| 3  | — | — | — | — | — | — | — |
| 4  | — | — | — | — | — | — | — |
| 5  | — | — | — | — | — | — | — |
| 6  | — | — | — | — | — | — | — |
| 7  | — | — | — | — | — | — | — |
| 8  | — | — | — | — | — | — | — |
| 9  | — | — | — | — | — | — | — |
| 10 | — | — | — | — | — | — | — |

### Profile Diversity Check

At least 4 of the 6 named profiles should be represented:
- [ ] Pattern Thinker
- [ ] Deep Diver
- [ ] Connector
- [ ] Builder
- [ ] Explorer
- [ ] Achiever

### Findings

| Profile # | Issue | Prompt Fix Applied |
|-----------|-------|-------------------|
| — | — | — |

---

## Sign-Off

- [ ] Automated check: all 5 criteria PASS
- [ ] Human review: ≥ 10 profiles reviewed, none flagged below 3
- [ ] Profile diversity: ≥ 4 of 6 labels represented
- [ ] Any failing profiles: prompt fix applied and re-tested

**Ready for real-student launch:** ☐ Yes  ☐ No — see Findings table

---

*This checklist is a BMAD AC for Story 4-33. A signed-off copy (with real profile data) is required before Sprint 4 closes.*
