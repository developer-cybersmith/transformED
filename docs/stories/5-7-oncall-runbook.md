# Story 5-7 — On-call runbook written (5 most likely failure scenarios)

Status: ready-for-dev

## Story

As an on-call developer (any of the 4 devs on the Week 10 rotation, `docs/dev1-tracker.md`
W10-3),
I want a written runbook that names the 5 most likely production failure scenarios and gives
each a short, concrete, already-tested resolution procedure grounded in this codebase's real
mechanisms (not generic ops advice),
so that whoever is paged at 2am can resolve — or safely triage — a real incident using what the
system actually does, instead of improvising against production for the first time during an
outage.

## Acceptance Criteria

1. `docs/ops/runbook.md` is created and committed (directory does not exist yet — verified,
   see Project Structure Notes). It supersedes the stale reference in
   `docs/bmad/epics/epic-5-platform-core.md` ("On-Call Runbook" section) at the same path.
2. The runbook covers, at minimum, the 5 scenarios named in `docs/dev1-tracker.md` S4-7 — the
   more specific, Dev-1-authoritative list, used as the mandatory floor over epic-5's shorter,
   partially-different 4-item list (see AC 4 for the reconciliation of the one item epic-5 names
   that dev1-tracker doesn't):
   - ARQ job stuck
   - Cost ceiling breach mid-pipeline
   - Redis unreachable
   - Supabase down
   - Pipeline node 500-loop
3. Each scenario entry has: a **detection** step (how an on-call engineer actually notices this,
   given today's real observability — see Scale & Load Q1/Q3), a **diagnosis** step naming the
   real endpoint/table/log to check, and **≤5 resolution steps** referencing real, currently-
   existing mechanisms in this codebase (not hypothetical tooling) — cited by file/endpoint in
   the entry itself. A step that cannot be executed against the real system as it exists today
   (e.g. a dashboard that doesn't exist per W10-2, or an admin action that has no endpoint) is
   not a valid resolution step; it is a follow-up gap to log, per AC 7.
4. The runbook contains an explicit **"6th scenario?" reconciliation section** addressing
   epic-5's "Stripe webhook failing" (absent from dev1-tracker's list, and not yet buildable
   today since no Stripe integration exists — see Project Structure Notes). It must state a
   concrete recommendation — add as a 6th full scenario, or fold as a sub-case into an existing
   entry — with reasoning, not leave the question open. This section is written/finalized only
   once Story 5-3 (S4-3, Stripe Checkout integration) has shipped enough to know the real webhook
   failure shape; see Sprint 4 Sequencing.
5. Each scenario's resolution steps incorporate real findings from Stories 5-1 and 5-2 (S4-1
   load test, S4-2 pipeline reliability fixes) wherever those stories touch the same failure —
   ARQ job stuck, cost ceiling breach, and node 500-loop are named failure modes S4-1/S4-2 are
   explicitly scoped to produce and fix. This runbook is not written from first-principles
   speculation about what might go wrong; it is written from what Sprint 4's own load test
   actually observed. See Sprint 4 Sequencing for the hard dependency this creates.
6. The Supabase-down entry links to the disaster-recovery procedure produced by Story 5-6
   (S4-6, Railway backups + DR tested) rather than duplicating restore steps inline — a second,
   drifting copy of a restore procedure is worse than a cross-reference (CLAUDE.md's drift
   concern, stated explicitly for the Scale Contract itself and equally true here).
7. A **"tested by" sign-off block** is present in the runbook (name, date, scenarios walked,
   gaps found) and is filled in by a teammate who did not author the runbook, before this story
   is marked done — tracked as an explicit Task (Task 5), not left as prose. A runbook untested
   by anyone but its own author is not accepted as done.
8. The runbook is committed as a plain markdown doc — no code changes ship with this story
   (this is a documentation deliverable; nothing in `apps/api` or `apps/web` is touched).

## Scale & Load

<!-- REQUIRED — see docs/SCALE-CONTRACT.md. Answer all six BEFORE writing Tasks/Subtasks.
     "N/A" is valid ONLY with a stated reason. A bare "N/A" is a missing answer.
     One-line test: "What input makes this silently wrong rather than loudly broken?" -->

1. **What is ONE unit of work, and what is its range?**
   One unit of work is one scenario entry in the runbook. Range: the mandatory floor is the 5
   dev1-tracker scenarios; the range tops out at 6 if AC 4's reconciliation decides Stripe
   webhook failure earns its own entry, or stays at 5 (with a Stripe sub-case folded into an
   existing entry) if it doesn't. There is no code-side "largest measured" here since this is a
   documentation artifact, not a data pipeline — the closest analogue is: 5 is the smallest
   acceptable set (the AC's floor), 6 is the realistic ceiling for this story, and a 7th
   scenario is out of scope for S4-7 (would need its own follow-up story, not silently appended
   here past the reconciliation this AC already scopes).

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   The fixed budget is dev1-tracker's own AC: **≤5 resolution steps per scenario**. The input
   that varies is real incident complexity — some failures (Supabase down) genuinely need more
   remediation depth than 5 flat steps can hold. The behavior past the limit must be an
   **explicit degradation, not a silently-shortened procedure**: this is precisely the failure
   class CLAUDE.md's "silent truncation is never acceptable" rule names, applied to a runbook
   instead of a token window — a runbook that quietly drops steps to fit a 5-step cap is
   dangerous in exactly the same way `structure_max_sections` silently dropping 96% of a book
   was. The explicit degradation adopted here: when a scenario's real remediation exceeds 5
   steps, the on-page entry stays ≤5 by linking out to a deeper doc for the overflow (the
   Supabase-down entry linking to 5-6's DR doc, per AC 6, is this pattern in practice) — the
   link itself is the 5th step, never a step silently omitted with no trace.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   The ≤5-step cap is scoped **per scenario entry**, not aggregated across the runbook (a
   6-scenario runbook is not a 30-step document capped as one unit). The runbook itself is
   scoped **per deployment** — today that means the single Railway deployment (no India-region
   migration completed yet per ADR-001, `CLAUDE.md`'s Development Rules); any Redis/Supabase
   URLs, admin-endpoint hosts, or Railway dashboard links the runbook names must be marked as
   this-environment-only so a future post-migration runbook update isn't a silent drift the way
   the Dev 1 tracker rule itself was silently dropped by an unrelated merge on 2026-07-28
   (`CLAUDE.md`, Sprint Tracker Auto-Update Rule).

4. **Which reads and writes are UNBOUNDED?**
   None in the runbook document itself (it is prose, not a query). But the *procedures it
   prescribes* must not tell an on-call engineer to run an ad hoc unbounded query against
   production under incident pressure — verified against real code: `reap_stale_lessons.py`'s
   own reaper query is already bounded (`_REAP_BATCH_LIMIT = 100`, `.limit()`), and
   `admin/router.py`'s `GET /jobs` / `GET /costs` endpoints are the correct, already-bounded
   surfaces for "what's stuck / what did this cost" diagnosis (the cost-report query itself was
   fixed to `.limit(10_000)` in Story 3-51/D59(a) — this runbook's cost-ceiling entry should
   point at that endpoint, not suggest a fresh raw `SELECT * FROM lesson_jobs`). The ARQ-stuck
   entry must not instruct a manual unbounded scan of `lesson_jobs`; it points at the existing
   bounded reaper and the existing bounded admin endpoints instead.

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   The ≤5-step-per-scenario cap itself is inherited from dev1-tracker's AC line, written before
   any scenario's real remediation depth was known. This story re-derives it explicitly rather
   than accepting it as a given: for 4 of the 5 mandatory scenarios (ARQ stuck, cost ceiling,
   Redis unreachable, node 500-loop) 5 steps is sufficient because the underlying mechanism is
   already automated or has a single admin endpoint to invoke (see Q4). For Supabase-down, 5
   steps is NOT sufficient for a real restore, which is why AC 6 re-derives the cap for that one
   entry specifically as "≤5 steps that include a link out," rather than silently stretching the
   inherited number or silently shrinking real DR content to fit it.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   Not applicable to the markdown document itself (no state, no race). But two of the real
   procedures the runbook will point to have a known, registered concurrency gap that the
   runbook MUST warn about rather than silently omit: (a) the admin job-retry endpoint
   (`POST /api/admin/jobs/{job_id}/retry`, Story 3-58) has no DB-level lock preventing two
   on-call engineers — or one engineer double-clicking — from retrying the same stuck job
   concurrently (registered as **D109**, deferred); the runbook's ARQ-stuck entry must say "one
   person retries, confirm status before a second attempt" rather than leave that race
   unstated. (b) the `(chapter_id, tier)` idempotency pre-check has no UNIQUE constraint (**D45**)
   — irrelevant to on-call remediation directly, but worth a one-line cross-reference if the
   cost-ceiling entry ever discusses re-triggering a lesson generation, so on-call doesn't
   accidentally double-bill a student while resolving an incident.

## Tasks / Subtasks

- [ ] Task 1 — Scaffold `docs/ops/runbook.md` (AC: 1, 8)
  - [ ] 1.1 Create `docs/ops/` (does not exist in the repo today — verified via `find`).
  - [ ] 1.2 Write the doc header: owner rotation reference (W10-3), environment scope note
        (single Railway deployment, no India region yet — ADR-001), links to
        `GET /api/admin/health` (deep_health) as the first diagnostic step for any incident.
  - [ ] 1.3 Add the "tested by" sign-off block (AC 7) as an empty template at the bottom of the
        doc, ready for Task 5.

- [ ] Task 2 — Write the 5 mandatory scenario entries (AC: 2, 3, 5, and Q1–Q6 of Scale & Load)
  - [ ] 2.1 **ARQ job stuck** — detection via `GET /api/admin/jobs` (status=running with a stale
        `started_at`) or waiting for the `reap_stale_generating_lessons` cron
        (`apps/api/app/workers/jobs/reap_stale_lessons.py`, runs at :00/:10/:20/:30/:40/:50,
        `arq_job_timeout_s`-bounded, D53/D91); resolution steps limited to: confirm via admin
        endpoint → let the reaper or the existing `POST /jobs/{job_id}/retry` endpoint act →
        verify `lesson_jobs.status`/`lessons.status` converge → escalate only if the reaper
        itself is not running (worker process down — cross-reference "Redis unreachable" below,
        since ARQ needs Redis). Incorporate S4-1/S4-2's real load-test findings on ARQ behavior
        under load once those stories land (AC 5) — do not write this entry from documentation
        alone.
  - [ ] 2.2 **Cost ceiling breach mid-pipeline** — detection via `GET /api/admin/costs`
        (bounded per Story 3-51/D59(a), `.limit(10_000)`, `truncated` flag) or
        `lesson_jobs.error` prefixed `cost_ceiling_exceeded:`; note the system's actual designed
        behavior is downshift-and-complete, not abort (`core/cost_tracker.py`'s
        `CostCeilingError`, `max_lesson_cost_usd = $3.00` default) — the runbook step is mostly
        confirm-this-is-expected-behavior, not "fix" a working control. Cross-reference D45 if
        the resolution ever involves manually re-triggering a lesson.
  - [ ] 2.3 **Redis unreachable** — detection via `GET /api/admin/health` (`deep_health`'s
        `redis` field) or Railway Redis dashboard; note real blast radius from actual code:
        ARQ cannot dequeue jobs at all, `core/circuit_breaker.py` and `core/cost_tracker.py`
        both depend on `get_redis()` (raises `RuntimeError` if `init_redis()` never completed),
        so this failure is upstream of "ARQ job stuck" and "cost ceiling," not independent of
        them — say so explicitly rather than presenting all 5 as siblings with no relationship.
  - [ ] 2.4 **Supabase down** — detection via `GET /api/admin/health`'s `supabase` field;
        resolution steps stay ≤5 by linking to Story 5-6's DR doc for the actual restore
        procedure (AC 6) rather than duplicating it — this entry's own steps are limited to
        confirm-and-communicate (status page / user-facing messaging), not restore mechanics.
  - [ ] 2.5 **Pipeline node 500-loop** — detection via Langfuse traces (if wired — verify
        against actual Sprint 0 wiring, don't assume) or repeated `lesson_jobs.node_outputs`
        entries for the same `last_node`; resolution references the REAL layered retry
        mechanism already in code: per-node `with_retry` (`core/retry.py`, 3 attempts critical /
        2 optional, exponential-backoff-with-jitter, retries only 429/500/502/503/504), the
        per-provider circuit breaker (`core/circuit_breaker.py`, opens after 5 failures/120s,
        half-open probe at 600s — Redis keys `circuit:{provider}:state` etc., manually
        resettable by deleting that key if a false-open is confirmed), and ARQ's own
        `max_tries=3` at the job level (`workers/main.py`) — a true infinite loop means all
        three layers failed to break it, which is itself the escalation trigger. Incorporate
        S4-2's real reliability-fix findings (AC 5) once landed.

- [ ] Task 3 — Write the "6th scenario?" reconciliation section (AC 4)
  - [ ] 3.1 Check Story 5-3's real shipped state (webhook handler exists? idempotency check
        implemented? per epic-5 §Payments, `stripe_session_id` de-dupe is the stated design).
  - [ ] 3.2 Write the recommendation with reasoning — do not leave "TBD" (CLAUDE.md's binding
        rule 5: a documented limitation with no decision is a defect wearing a decision's
        clothes; the same standard applies to an undecided reconciliation in a runbook).
  - [ ] 3.3 If recommending inclusion as a 6th scenario, write it to the same ≤5-step,
        detection/diagnosis/resolution shape as the other 5. If recommending a merged sub-case,
        state which existing entry it merges into and why (most likely candidate: it's a
        webhook delivery failure, not a pipeline failure — may not fit any of the 5 cleanly,
        which is itself part of the reasoning to write down).

- [ ] Task 4 — Correct the epic-5 path/detail drift found during research (AC: 1, 8; Dev Notes)
  - [ ] 4.1 Note in the runbook's header (or in this story's Dev Notes, not silently) that
        epic-5's Technical Scope table names `backend/routers/payments.py` for the payments
        router — this repo's real, verified convention is
        `apps/api/app/modules/{module}/router.py` (confirmed via `apps/api/app/modules/admin/
        router.py`, `apps/api/app/modules/content/pipeline/`, etc.); no `payments` module
        exists in the repo yet at all (verified: no file matching `*payment*`/`*stripe*` under
        `apps/api/app`). This matters directly for Task 3 since the eventual Stripe webhook
        handler this reconciliation discusses will live at
        `apps/api/app/modules/payments/router.py`, not the path epic-5 names.

- [ ] Task 5 — Independent teammate test (AC: 7)
  - [ ] 5.1 Identify a teammate who did not author the runbook.
  - [ ] 5.2 Have them walk all 5 (or 6) scenarios against the real admin endpoints / real Redis
        keys / real `docs/ops/` links named in the doc — either live against a non-prod
        environment or a structured dry-run reading each step against actual running code —
        and record what did NOT work as written.
  - [ ] 5.3 Fix every gap found before considering the AC satisfied; fill in the sign-off block
        (Task 1.3) with their name, date, and a one-line note per scenario walked.
  - [ ] 5.4 Only after 5.3 is complete does this story move out of `ready-for-dev`.

## Dev Notes

- This is a **documentation-only** story — no `apps/api` or `apps/web` code changes ship with
  it. The "testing standard" for this story is the human-verification process in Task 5, not an
  automated test suite; there is nothing to add to `tests/unit/` for this story itself.
- Every mechanism cited in the runbook was verified against real code during story research,
  not assumed from `docs/dev1-tracker.md` or `docs/bmad/epics/epic-5-platform-core.md` prose
  alone (both were checked, and epic-5 was found to name at least one stale path — Task 4). This
  matches the project's established lesson (`CLAUDE.md`'s Defect Register section): "9 of 11
  pre-existing defects never worked for one minute" because prose descriptions were trusted
  without checking the code behind them.
- Real mechanisms confirmed to exist and usable in the runbook (do not re-describe from memory
  when writing the actual doc — re-read each file to keep the runbook accurate as code changes
  under S4-1/S4-2):
  - `apps/api/app/workers/jobs/reap_stale_lessons.py` — the D53/D91 stale-job reaper, cron at
    `:00/:10/:20/:30/:40/:50`, bounded `_REAP_BATCH_LIMIT = 100`.
  - `apps/api/app/modules/admin/router.py` — `GET /jobs`, `GET /jobs/{job_id}`,
    `POST /jobs/{job_id}/retry` (Story 3-58), `GET /costs` (bounded per D59(a)/Story 3-51),
    `GET /health` (`deep_health` — the ONLY existing live probe of Redis + Supabase reachability
    in this codebase today).
  - `apps/api/app/core/cost_tracker.py` — `check_ceiling()`, `CostCeilingError`,
    `max_lesson_cost_usd` default `$3.00`, Redis key `cost:{lesson_id}`.
  - `apps/api/app/core/circuit_breaker.py` — per-provider Redis keys
    `circuit:{provider}:{state,failures,opened_at}`, 5-failures/120s open threshold, 600s
    half-open recovery; no code-level manual-reset function exists, so a forced reset is a
    direct Redis `DEL` on `circuit:{provider}:state` — state this plainly in the runbook rather
    than implying a nonexistent admin action.
  - `apps/api/app/core/retry.py` — per-node backoff (3 attempts critical / 2 optional,
    `(2**attempt) + random()` jitter), retryable set `{429,500,502,503,504}`, non-retryable
    `{400,401,403,404,422}`.
  - `apps/api/app/workers/main.py` — ARQ `WorkerSettings`: `max_tries=3`, `job_timeout` from
    `settings.arq_job_timeout_s` (default 1800s).
- What does **not** exist yet, and must not be assumed by the runbook: a live monitoring
  dashboard (`DeepHealthStatus.worker_queue_depth` is hardcoded `None` — nobody has wired real
  queue-depth reporting; W10-2 "Monitoring dashboards live" is a separate, later, not-yet-done
  task), any PagerDuty/paging integration (grepped — none found anywhere in `docs/`), a
  `payments`/Stripe module of any kind (Story 5-3/S4-3 not started), and `docs/ops/`,
  `docs/security/rls-audit.md`, or any disaster-recovery doc (Story 5-6/S4-6 not started) at
  all. The runbook's detection steps must therefore describe **manual, admin-endpoint-driven**
  detection today, not "you'll get paged" — that would misrepresent a capability that does not
  exist and could leave a real on-call engineer waiting for an alert that will never fire.

### Project Structure Notes

- Alignment: `docs/ops/runbook.md` (the path epic-5 already names) matches this repo's
  documentation convention (`docs/{topic}/`) — no correction needed for the runbook's own path.
- Variance found and corrected: epic-5's Technical Scope table lists the payments router at
  `backend/routers/payments.py`. This repo has no `backend/` directory at all — the real,
  verified convention (confirmed against `apps/api/app/modules/admin/router.py`,
  `apps/api/app/modules/content/pipeline/`) is `apps/api/app/modules/{module}/router.py`. No
  `payments` module exists yet in the repo. This is called out because Task 3/Task 4 of this
  story reference where a future Stripe webhook handler will live when reasoning about the 6th-
  scenario question — the story does not silently inherit epic-5's stale path into the runbook.
- No other path claims in epic-5's runbook-adjacent sections (`docs/ops/runbook.md`,
  `docs/security/rls-audit.md`) needed correction — both are stated as not-yet-created, which
  matches the repo as found.

### References

- [Source: docs/dev1-tracker.md#Sprint-4 — S4-7 "On-call runbook written", the authoritative
  5-scenario list and the ≤5-step / tested-by-a-teammate AC]
- [Source: docs/bmad/epics/epic-5-platform-core.md#On-Call-Runbook — the 4-scenario list
  including "Stripe webhook failing", reconciled in AC 4/Task 3]
- [Source: docs/bmad/epics/epic-5-platform-core.md#Technical-Scope — stale `backend/routers/
  payments.py` path, corrected in Project Structure Notes]
- [Source: CLAUDE.md#Development-Rules — silent truncation rule, applied to the ≤5-step cap in
  Scale & Load Q2]
- [Source: CLAUDE.md#Defect-Register — "9 of 11 pre-existing defects never worked for one
  minute" / "prose guidance does not hold", the standard this story's research holds itself to]
- [Source: docs/SCALE-CONTRACT.md#The-six-questions — full text behind the Scale & Load section]
- [Source: docs/DEFECT-REGISTER.md#D109 — admin job-retry endpoint has no DB-level lock,
  cited in Scale & Load Q6]
- [Source: docs/DEFECT-REGISTER.md#D45 — `(chapter_id, tier)` idempotency has no UNIQUE
  constraint, cross-referenced in the cost-ceiling entry]
- [Source: docs/DEFECT-REGISTER.md#D53 / #D91 — the stale-`generating`-lesson reaper this
  story's ARQ-stuck entry points to instead of a manual query]
- [Source: docs/stories/3-58-admin-job-retry-endpoint.md — confirms `admin/router.py`'s real
  existing endpoints: `GET /jobs`, `GET /jobs/{job_id}`, `POST /jobs/{job_id}/retry`,
  `GET /costs`, `GET /health`]
- [Source: docs/stories/3-51-d59a-admin-cost-bounded.md — confirms `GET /costs` is bounded
  (`.limit(10_000)`, `truncated` flag), used in the cost-ceiling entry]
- [Source: apps/api/app/workers/jobs/reap_stale_lessons.py — D53/D91 reaper, cron schedule,
  `_REAP_BATCH_LIMIT`]
- [Source: apps/api/app/modules/admin/router.py — `deep_health`, real Redis/Supabase probe]
- [Source: apps/api/app/core/cost_tracker.py — `check_ceiling`, `CostCeilingError`,
  `max_lesson_cost_usd`]
- [Source: apps/api/app/core/circuit_breaker.py — per-provider Redis key schema, thresholds]
- [Source: apps/api/app/core/retry.py — per-node retry/backoff rules]
- [Source: apps/api/app/workers/main.py — ARQ `WorkerSettings` (`max_tries`, `job_timeout`)]
- [Source: apps/api/app/config.py — `max_lesson_cost_usd` default, `arq_job_timeout_s` default]

## Sprint 4 Sequencing

- **Branch:** `sprint4/s4-7-oncall-runbook`
- **Depends on:**
  - **5-1** (S4-1, load test) — real observed failure modes for ARQ-stuck, node-500-loop, and
    cost-ceiling-under-load feed the runbook's resolution steps; writing this runbook before
    5-1 runs means guessing at behavior instead of documenting it.
  - **5-2** (S4-2, pipeline reliability fixes) — the runbook should describe the system's
    *fixed* post-S4-2 behavior (retry exhaustion, Redis-connection-drop handling, node timeout
    under load), not the pre-fix bugs S4-1 will surface; sequencing after 5-2 avoids writing a
    runbook entry for a bug that gets fixed out from under it mid-sprint.
  - **5-3** (S4-3, Stripe Checkout integration) — required to resolve AC 4's "6th scenario?"
    reconciliation with real information about how the webhook handler actually fails, rather
    than a guess made before the integration exists.
  - **5-6** (S4-6, Railway backups + DR tested) — the Supabase-down entry links to 5-6's DR doc
    (AC 6) instead of duplicating it; that doc must exist first.
  - This story is intentionally sequenced **last or near-last** among Sprint 4's 8 tasks — a
    runbook is only as good as the failure modes actually observed, and this story is the one
    most of whose Tasks explicitly incorporate real findings from other Sprint 4 stories rather
    than being writable in isolation (see Dev Notes and Task 2's per-scenario notes).
- **Blocks:**
  - **W10-3** (Week 10, "On-call rotation established") — the roadmap's own AC is "runbook link
    shared with all," which cannot happen before this story ships.
  - No other Sprint 4 story (5-1 through 5-6, 5-8) depends on this one completing first — S4-7
    is a leaf node in the Sprint 4 dependency graph, consistent with its "last or near-last"
    sequencing.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
