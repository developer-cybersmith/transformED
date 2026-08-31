# Sprint 4 — Student Drop-off Funnel Analysis

**Author:** Dev 3 (tannmayygupta)  
**Date:** 2026-08-31  
**Story:** 4-7  
**Data source:** Supabase — `sessions`, `quiz_attempts`, `teachback_attempts`, `session_events`  
**Date range:** 2026-08-10 to 2026-08-26 (all sessions ever run)  
**Sample size:** 117 sessions  

---

## Data Source Note — Why Not PostHog

PostHog received **zero events** across all 117 sessions. Root cause: `POSTHOG_API_KEY` was never set in the Railway production environment. `posthog_client.capture_event()` has a silent-skip guard (`if not posthog.api_key: return`) — correct defensively but meant the entire analytics pipeline was silently inert from day one. This is registered as a new defect (see §Defects Revealed below).

The funnel is reconstructed from the app's relational tables, which are the authoritative source:

| Funnel step | Data source | Proxy definition |
|---|---|---|
| session_start | `sessions.started_at IS NOT NULL` | Session row created and player initialised |
| quiz_submitted | `quiz_attempts` row with this `session_id` | Student submitted ≥1 quiz answer |
| teachback_submitted | `teachback_attempts` row with this `session_id` | Student submitted typed teach-back |
| session_end | `sessions.ended_at IS NOT NULL` | `complete_session` REST call reached |

---

## Funnel Results

```
Step 1  session_start        117  (100.0%)
        ↓ dropped: 106         ← 90.6% DROP-OFF ← HIGHEST
Step 2  quiz_submitted         11  (  9.4%)
        ↓ dropped:  10         ← 90.9% drop-off (of those who reached Step 2)
Step 3  teachback_submitted     1  (  0.9%)
        ↓ dropped:   0          
Step 4  session_end             4  (  3.4%)  *
```

\* Step 4 (4 sessions) is non-sequential relative to Steps 2–3: the 4 sessions that reached `ended_at` are all Stage 2 (quiz) sessions. None of the 106 Stage 1 sessions ever received an `ended_at` write, confirming they were abandoned in the player before `Player.tsx` fired `complete_session`.

### Conversion table

| Transition | Entered | Converted | Conversion % | Drop-off % |
|---|---|---|---|---|
| session_start → quiz_submitted | 117 | 11 | 9.4% | **90.6%** |
| quiz_submitted → teachback_submitted | 11 | 1 | 9.1% | 90.9% |
| teachback_submitted → session_end | 1 | 1 | 100% | 0% |

### Stage distribution (all 117 sessions)

| Stage reached | Count | % of total |
|---|---|---|
| stage1_only (never reached quiz) | 106 | 90.6% |
| stage2_quiz (quiz only) | 10 | 8.5% |
| stage3_teachback | 1 | 0.9% |

---

## Weekly Volume

| Week of | Sessions | Completed (ended_at) | With ces_final |
|---|---|---|---|
| 2026-08-10 | 86 | 1 | 0 |
| 2026-08-17 | 29 | 3 | 0 |
| 2026-08-24 | 2 | 0 | 0 |
| **Total** | **117** | **4** | **0** |

Note: `ces_final` = 0 on all sessions across all weeks — pre-D116 fix (Story 4-6, merged 2026-08-31). The Aug-10 spike (86 sessions in one week) is a bulk internal test burst, not a sustained usage pattern.

---

## Step With Highest Drop-off

**Step 1 → Step 2 (session_start → quiz_submitted): 90.6% drop-off.**

106 of 117 sessions never submitted a single quiz answer. This is the dominant failure — everything downstream of it is noise by comparison.

---

## Top 2 Drop-off Hypotheses

### Hypothesis 1 — Lesson content never reached the quiz slide (most likely)

**Claim:** Sessions dropped at Stage 1 not because testers quit voluntarily, but because the player could not reach the quiz slide — either audio failed to load, the lesson package was malformed for those sessions, or the player state machine stalled before the first quiz segment.

**Supporting evidence:**
- 106 sessions have `quiz_attempts = 0`. If the quiz widget was rendered and testers chose not to answer, we would expect some non-zero attempts (even abandoned ones are recorded). Zero attempts means the quiz was never surfaced.
- `session_events` for those 106 sessions contains only `tab_switch` and `intervention_triggered` — confirming the player was running (CES was active) but never reached a quiz slide.
- The 10 sessions that did reach quizzes have 3–6 quiz attempts each (not just 1), showing testers who got to quizzes actually engaged with them. The drop is binary — either the quiz was reachable or it wasn't.
- ces_final was NULL on all sessions (pre-D116) meaning the session-end flow was also broken — both the quiz path and the session-end path were severed, consistent with a pipeline/player delivery issue rather than user abandonment.

**Implication:** Fix is NOT in the quiz UI. It is upstream — verify `package_builder` output has correctly formed segments with quiz data that the player can render, and verify audio URLs are accessible.

### Hypothesis 2 — Session rows are cheap API artefacts, not real lesson attempts

**Claim:** A significant portion of the 117 sessions were created by developer API calls, curl tests, or player page loads that never progressed through a real lesson, inflating the "started" count.

**Supporting evidence:**
- 86 sessions in a single week (Aug 10) is implausibly high for a team of 4 doing manual testing. This is consistent with automated API tests or a load-testing script that creates sessions without running the full lesson flow.
- All 86 of those sessions are Stage 1 — not a single quiz was attempted that week. A real lesson attempt by a tester working on quiz functionality would produce at least some quiz_attempts.
- Sessions have `started_at` set but most lack `ended_at` — consistent with a row being created via REST and the player never being opened.

**Implication:** The true drop-off rate from *real lesson attempts* is unknown. Before Sprint 5, establish a baseline of sessions where `started_at` is set AND at least one `session_events` row exists (proves the player was actually open) to filter out API-only sessions. The clean funnel likely shows a much smaller denominator with a similar or higher conversion rate.

---

## Secondary findings

### Finding 3 — Teachback engagement near-zero

Of the 11 sessions that reached quizzes, only 1 (9.1%) submitted a teachback. The teach-back step is after quizzes and requires typed text — more cognitive effort than clicking a multiple-choice answer. With so few sessions reaching this step, no statistically meaningful conclusion can be drawn. Re-evaluate after 20+ real sessions with consistent quiz completion.

### Finding 4 — PostHog pipeline was silent from day one (new defect)

`POSTHOG_API_KEY` is unset → 0 events received by PostHog. The dashboard is empty. This defect means all previous sprint work that claimed to send PostHog events has been inert. This must be fixed before Sprint 4 calibration tasks can use PostHog as a data source.

Defect registered: see `docs/DEFECT-REGISTER.md` D118.

### Finding 5 — ces_final NULL on all historical sessions

All 117 sessions have `ces_final = NULL`. Explained and fixed by D116 (Story 4-6, 2026-08-31). Future sessions will have ces_final written correctly. Historical data cannot be retroactively repaired (ces_history in Redis was not persisted after session end, so the averaging window is gone).

---

## Caveats

1. **PostHog unavailable.** Funnel is 100% reconstructed from Supabase tables. This is equivalent in information content for quiz/teachback steps, but cannot provide time-to-event, user path, or page-level analytics.
2. **No user de-duplication.** The analysis is session-scoped, not user-scoped. A single tester running 10 sessions counts as 10 sessions.
3. **Internal testing data only.** All 117 sessions are internal team tests, not real students. Drop-off patterns may differ substantially under real usage.
4. **ces_final always NULL (pre-fix).** CES-correlated drop-off analysis is not possible on this historical dataset.
5. **Sample size.** 11 sessions reaching quiz and 1 reaching teachback is too small for statistical significance. Conclusions are directional, not definitive.

---

## Recommended Actions (by priority)

| Priority | Action | Owner |
|---|---|---|
| P0 | Set `POSTHOG_API_KEY` in Railway env vars (D117) | Dev 1 / Infra |
| P1 | Audit `package_builder` output for the 106 Stage-1 sessions — check if lesson packages were complete | Dev 1 |
| P1 | Run 20 real sessions with PostHog active to get clean funnel data | All devs |
| P2 | Add a `player_opened` event to session_events so API-created sessions can be distinguished from real lesson attempts | Dev 2 |
| P3 | After 20 clean sessions, re-run this analysis with D116 fixed and PostHog active | Dev 3 |
