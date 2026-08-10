# ADR-001 — India-region migration: deployment topology

**Status:** 🟡 **PROPOSED — provider choice needs sign-off; topology and Langfuse are decided**
**Date:** 2026-07-30 · **Owner:** Dev 1 (`docs/master-tracker.md:204` assigns this migration to Dev 1)
**Supersedes:** nothing. **Referenced by:** `CLAUDE.md:201`, `docs/bmad/epics/epic-5-platform-core.md:153`, `docs/master-tracker.md:204`

---

## Why this document exists

A reviewer asked two topology questions:

> *"Is Langfuse still self-hosted as a 3rd service, or moved to Langfuse Cloud? And do API + worker
> genuinely stay split on Fly (two separate Fly apps) or get consolidated into one?"*

Neither question could be answered from the repo, for two different reasons — and that is the
problem this ADR closes.

**Question 1 had an answer, but the repo contradicted itself about it.** Langfuse is on Cloud, and
`.env.example` says otherwise.

**Question 2 had no answer at all.** Every mention of Fly in this repo is the *same sentence*,
copied into three files, listing Fly as one of **three candidates**:

> *"migrate FastAPI/ARQ to India-region provider before Sprint 3 real-student launch
> (**Fly.io Mumbai, Render Singapore, or AWS ap-south-1**)"*

There is **no `fly.toml`, no Fly configuration, and no Fly deployment document anywhere in git
history.** So anyone presenting "a Fly topology" is proposing one, not describing one. Asking
whether the API and worker *"still"* stay split on Fly presumes a design that does not exist.

**Three copies of a sentence listing options is not a decision.** This ADR is the decision.

---

## 1. DECIDED — Langfuse runs on Langfuse Cloud. It is not a service we deploy.

| Source | Value | Verdict |
|---|---|---|
| `apps/api/app/config.py:87-88` (code default) | `https://cloud.langfuse.com` | ✅ correct |
| `apps/api/.env` (live) | `LANGFUSE_HOST=https://cloud.langfuse.com` | ✅ correct — **this is what runs today** |
| `.env.example:41` | `LANGFUSE_HOST=http://localhost:3010` | ❌ **stale and misleading** |

Langfuse is reached as an **outbound HTTPS SDK call** from the API and worker processes. There is
nothing to deploy, nothing to scale, no port to expose, and **no third service in any topology
diagram.**

Tracing is also already **best-effort by design** — `core/langfuse.py` degrades to no-tracing if
init fails, and `_safe_trace()` guarantees an observability outage can never fail a pipeline run.
So Langfuse is not on the availability critical path either.

### Required action (a real defect, not just a doc fix)

`.env.example:41` must be corrected to `https://cloud.langfuse.com`. Anyone provisioning an
environment from that template would reasonably conclude Langfuse is self-hosted on port 3010 —
**which is exactly the confusion that produced the reviewer's question.**

This is the **second wrong value in that same file** this week. The first —
`NEXT_PUBLIC_API_URL` missing its `/api` path segment — 404s *every* frontend API call and is
registered as **D31**. Both are Dev 1's and should be fixed in one change, because the failure
mode is identical: **the documented setup path is wrong while the code default is right, so
whoever follows the instructions is worse off than whoever ignores them.**

---

## 2. DECIDED — API and worker stay separate processes. This is not a preference.

They are separate today (`railway.toml`): three Railway services sharing one Dockerfile —
API (`uvicorn`, `numReplicas = 2` in production), worker
(`python -m arq app.workers.main.WorkerSettings`), and web from `apps/web`.

They must stay separate, for reasons measured rather than assumed:

| Constraint | Measured value | Consequence of consolidating |
|---|---|---|
| **Job duration** | `arq_job_timeout_s = 1800` (30 min); extract alone capped at `extract_timeout_cap_s = 1500` (25 min) | A web request timeout or a routine redeploy kills in-flight generation that has **already been paid for** in AI spend. Up to $3.00/lesson, discarded. |
| **Memory profile** | Extraction peaked at **≤1.95 GB** (Sprint 1, live-measured); the API is I/O-light | One VM must be sized for the worker's peak, so every API replica pays for memory it never uses. |
| **Scaling shape** | Worker `max_jobs = 5` concurrent; API is bursty and request-scaled | Coupled scaling means scaling for traffic over-provisions generation capacity, and vice versa. |
| **Failure isolation** | Worker OOM during a 1,120-page extraction is a known, survivable event | Consolidated, it takes the API — and every live WebSocket — down with it. |

There is a **contract-tested invariant** protecting the first row:
`arq_job_timeout_s >= extract_timeout_cap_s + 300` (`config.py:384`). Consolidation would put a
web server's request lifecycle inside that budget, where it does not belong.

---

## 3. PROPOSED — one Fly app with two process groups, not two Fly apps

**This is the answer to the reviewer's actual question:** separate *processes*, yes — separate
*apps*, no.

Fly supports multiple process groups in a single `fly.toml`. Each group gets its own machines,
its own VM size, and its own scaling, from **one app, one image, one deploy, one secrets set, and
shared internal networking**.

```toml
# fly.toml — illustrative, not yet committed
app = "hie-api"
primary_region = "bom"          # Mumbai

[build]
  dockerfile = "apps/api/Dockerfile"

[processes]
  api    = "uvicorn app.main:app --host 0.0.0.0 --port 8080"
  worker = "python -m arq app.workers.main.WorkerSettings"

[http_service]
  internal_port = 8080
  processes = ["api"]           # only the API takes public traffic
  auto_stop_machines  = false    # NEVER true for the worker — see §5
  min_machines_running = 1

[[vm]]
  processes = ["api"]
  size = "shared-cpu-2x"        # 2 GB

[[vm]]
  processes = ["worker"]
  size = "performance-2x"       # 4 GB — headroom over the 1.95 GB measured peak

[checks.api]
  path = "/health"              # already implemented; railway.toml uses it today
```

**Why this shape maps cleanly onto what we already have:** the Dockerfile's `CMD` is the API
command (`Dockerfile:68`) and the worker already runs by overriding the start command. That is
precisely the one-image/two-commands model process groups are designed for. Two separate Fly apps
would duplicate the deploy, the secrets, and the image push for zero benefit.

### A non-obvious property worth recording: no sticky sessions are needed

WebSockets terminate on the API process, and `lesson_ready` reaches clients via Redis pub/sub. The
listener is started **per API process** (`main.py:94`), so with N API machines, all N subscribe and
each delivers only to the connections it happens to hold.

**This is already the correct fan-out pattern.** It means API machines can scale horizontally with
**no session affinity, no sticky routing, and no shared WebSocket registry.** Anyone designing the
Fly load balancer config should know this so they do not add affinity that isn't needed — and,
more importantly, should not assume a single API machine.

---

## 4. HARD REQUIREMENT — Redis moves in the same change, or the migration makes things worse

Redis is not a cache here. **13 modules depend on it:**

| Use | Module |
|---|---|
| ARQ job queue | `workers/`, `modules/content/router.py` |
| Per-lesson cost tracking + the $3.00 ceiling | `core/cost_tracker.py` |
| Circuit-breaker state | `core/circuit_breaker.py` |
| `lesson_ready` pub/sub | `core/pubsub.py`, `workers/jobs/content_pipeline.py` |
| WebSocket connection registry | `core/websocket.py` |
| Tutor FSM state + intervention cooldowns | `modules/tutor/` |
| CES baseline buffer | `modules/assessment/ces_baseline.py` |
| Onboarding idempotency, re-assessment flags | `modules/assessment/` |

Redis is **Railway Redis** today. Moving compute to Mumbai while leaving Redis on Railway puts
every queue operation, every cost-tracker increment, every breaker check and every pub/sub message
across the public internet on a hot path.

**That is not a partial migration — it is a regression.** Latency would get worse, not better, and
the failure surface grows: a cross-region blip now hits eight subsystems instead of none.

Redis must land in the same region in the same change. Candidates: **Upstash (Mumbai)** or
**Fly Redis / Upstash-on-Fly**. Note also that we recently fixed the retry classification so a
Redis blip is survivable (**D19/D20**) — that fix makes a migration safer, but it is not a licence
to run Redis a continent away.

Supabase is already `ap-south-1` (Mumbai) per `epic-5-platform-core.md:153`, so the database side
of the residency requirement is satisfied. **Compute and Redis are the gap.**

---

## 5. Migration checklist (the things that will bite)

1. **`auto_stop_machines` must be `false` for the worker group.** Fly's scale-to-zero is designed
   for request-driven services. A worker machine stopped mid-job discards up to 30 minutes of
   paid-for generation. This is the single easiest way to turn a cost saving into a cost increase.
2. **Redis in-region, same change** (§4). Non-negotiable.
3. **Health check** — `/health` already exists and is already used by `railway.toml`. Reuse it;
   scope it to the `api` group only, since the worker exposes no HTTP port.
4. **Worker VM sized above 1.95 GB.** That was the *measured* extraction peak on a 41-page
   chapter. The 1,120-page full-book run needed a raised timeout cap (`EXTRACT_TIMEOUT_CAP_S=5400`
   session-level) and more headroom — if full-book ingestion is ever a product path rather than a
   proof, this number must be re-measured, not extrapolated.
5. **Secrets parity.** One `fly secrets set` for the app covers both process groups — an advantage
   of one app over two. Audit against `config.py`'s required fields; a missing key surfaces at
   worker start, not at deploy.
6. **The `$3.00/lesson` ceiling is enforced but has never been measured.** The cost meter landed
   2026-07-30 and the live eval has never run. **Do not size machines or model spend against any
   existing cost figure** — they all predate the 16× duplication fix and are ~4× inflated.
7. **`.env.example` must be corrected first** (§1 + D31), or every environment provisioned during
   the migration inherits two wrong values.
8. **Egress/data-residency review.** The residency requirement is about student data at rest and in
   transit. Moving compute to Mumbai while AI providers remain US-hosted is expected and unchanged —
   but it should be stated explicitly in the DPDP assessment rather than assumed, and it interacts
   with **D29** (the consent audit row still has no writer).

---

## 6. What is NOT decided here, and needs sign-off

**Provider choice.** This ADR proposes the *topology*; it does not pick the vendor. The three
candidates in `CLAUDE.md:201` have not been costed against each other, and I have not been asked
to. What is now settled is that whichever is chosen:

- Langfuse is not part of it (§1)
- API and worker are separate processes (§2)
- Redis moves with them (§4)

If Fly is chosen, §3 is the recommended shape. Render and AWS have equivalents (Render background
workers; ECS services or App Runner + a separate task), and the same three constraints apply.

**Timing.** `CLAUDE.md:201` makes this a hard prerequisite **before real students join in Sprint 3**,
because it is a **data-residency requirement, not a latency optimisation.** Nothing has started.

---

## Appendix — evidence for every claim above

| Claim | Verify at |
|---|---|
| Langfuse default is Cloud | `apps/api/app/config.py:87-88` |
| Langfuse live value is Cloud | `apps/api/.env` → `LANGFUSE_HOST` |
| `.env.example` is stale | `.env.example:41` |
| Tracing is best-effort | `apps/api/app/core/langfuse.py`, `_safe_trace` in `providers/llm/openai.py` |
| API/worker split today | `railway.toml` (header comment + `[deploy]`) |
| One image, two commands | `apps/api/Dockerfile:68` (`CMD` = API) |
| `arq_job_timeout_s = 1800`, `extract_timeout_cap_s = 1500` | `apps/api/app/config.py` |
| Timeout invariant | `apps/api/app/config.py:384` |
| Worker concurrency `max_jobs = 5` | `apps/api/app/workers/main.py:111` |
| Pub/sub listener per API process | `apps/api/app/main.py:94` |
| 13 Redis-dependent modules | `grep -rl "get_redis\|Redis.from_url" apps/api/app/` |
| Supabase in `ap-south-1` | `docs/bmad/epics/epic-5-platform-core.md:153` |
| Migration owned by Dev 1 | `docs/master-tracker.md:204` |
| Cost figures unreliable | `docs/DEFECT-REGISTER.md` → D1; `docs/reports/SPRINT-2-REPORT-dev1.md` §5 |
| `.env` `NEXT_PUBLIC_API_URL` defect | `docs/DEFECT-REGISTER.md` → D31 |
