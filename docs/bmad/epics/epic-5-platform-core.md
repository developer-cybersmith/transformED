# Epic 5: Platform Core (Auth + Payments + Admin)

| Field | Value |
|---|---|
| Epic ID | E-05 |
| Status | Planned |
| Owner | All devs (primarily Dev 1 + Dev 4) |
| Target Sprints | Sprint 2â€“4 (Weeks 4â€“9) |
| Priority | P1 â€” required for first paying student |

---

## Problem Statement

Without auth, payments, and a hardened production environment, HIE is a demo. A student cannot sign up independently, cannot pay for a lesson, and cannot receive their results without a developer manually assisting. This epic closes that gap â€” it turns the working prototype into a product that a real student can use end-to-end without any developer involvement.

---

## Goal / Success Metric

> **A brand-new user can discover HIE, sign up, complete Learner DNA onboarding, pay for a lesson, upload a PDF, complete the lesson, and receive their session report â€” with zero developer intervention and full DPDP Act compliance.**

---

## User Stories

- As a **prospective student**, I can land on the homepage, understand the product value, and sign up in under 2 minutes.
- As a **student**, I must complete the Learner DNA onboarding before I can upload my first lesson (platform gate).
- As a **student**, I can pay for a lesson using a hosted Stripe checkout page â€” my card details never touch HIE's servers.
- As a **student**, I receive an email when my lesson is ready and another email with my session report link.
- As an **admin**, I can view all running and failed pipeline jobs, their costs, and retry a failed job.
- As an **admin**, I can see all users, their lesson counts, and payment status.
- As a **platform operator**, I am confident that every database table has correct Row Level Security enforced.

---

## Auth Flow

### Provider
Supabase Auth (email/password + Google OAuth via Supabase provider).

### Onboarding Gate
After email verification â†’ redirect to `/onboarding` (Learner DNA 20-question flow, Epic 3).
`learner_dna.completed_at` is `NULL` until onboarding submitted.
Middleware (`middleware.ts`) checks `learner_dna.completed_at`; any route under `/lesson` or `/upload` redirects to `/onboarding` if NULL.

### Auth Routes

| Route | Behavior |
|---|---|
| `/auth/signup` | Email + password form; Supabase `signUp()`; triggers verification email |
| `/auth/signin` | Email + password; Supabase `signInWithPassword()` |
| `/auth/callback` | OAuth callback handler (Google); sets session cookie |
| `/auth/signout` | `supabase.auth.signOut()`; clears cookie; redirect to `/` |

### Session Handling
- Supabase client-side session via `@supabase/ssr` (Next.js 14 App Router)
- JWT passed in `Authorization: Bearer` header to FastAPI WebSocket + REST endpoints
- FastAPI validates JWT locally (PyJWT + `SUPABASE_JWT_SECRET`) on all protected routes

---

## Payments

### Provider
Stripe Checkout (hosted) â€” no card data on HIE servers under any circumstances.

### Flow

```
Student clicks "Buy Lesson"
  â””â”€â–º POST /api/payments/create-checkout-session
        â””â”€â–º Stripe creates hosted checkout session
              â””â”€â–º Student enters card on stripe.com
                    â”œâ”€â–º Success â†’ stripe.com redirects to /payment/success?session_id=...
                    â””â”€â–º Cancel  â†’ stripe.com redirects to /payment/cancel
  
Stripe webhook â†’ POST /api/payments/webhook
  â””â”€â–º Verify Stripe-Signature header (STRIPE_WEBHOOK_SECRET)
        â””â”€â–º On checkout.session.completed:
              â””â”€â–º Write lesson_access record â†’ unlock upload for user
```

### Lesson Access Gating
- `lesson_access` table: `{ user_id, lesson_credits, updated_at }`
- Upload endpoint (`POST /api/pipeline/submit`) checks `lesson_credits > 0` before queuing job
- On job submission, decrement `lesson_credits` by 1 (atomic DB update)
- RLS: users can only read their own `lesson_access` row

### Key Constraints
- Stripe Checkout (hosted) only â€” no Stripe Elements, no card data on our servers
- `STRIPE_WEBHOOK_SECRET` validated on every webhook call â€” unsigned webhooks rejected with 400
- Idempotency: webhook handler checks if `stripe_session_id` already processed to prevent double-credit

---

## Email Notifications

| Trigger | Template | Sender |
|---|---|---|
| Lesson package ready | "Your lesson is ready! [Open Lesson]" | Resend (transactional) |
| Session report available | "Here's how you did â€” [View Report]" | Resend (transactional) |
| (Optional) Welcome email | "Welcome to HIE" | Resend (transactional) |

- Email sending is an ARQ background job (not blocking API response)
- Templates stored in `backend/notifications/templates/`
- Resend API key in Railway env vars

---

## Admin Panel

Accessible at `/admin` â€” protected by `is_admin = true` flag in Supabase `profiles` table.

| Section | Data Shown | Key Actions |
|---|---|---|
| Job Monitor | All `lesson_jobs` rows: status, node, duration, cost | Retry failed job |
| Cost Tracker | Per-job LLM spend; daily/weekly totals | Export CSV |
| User Management | All users: email, lesson count, DNA completed, credits | Manual credit grant |
| Failed Jobs | Jobs with `status = 'failed'` and `error_message` | View traceback, retry |

Admin panel is a Next.js route group `(admin)` with a layout that checks `is_admin` server-side. No dedicated admin framework â€” plain Next.js + Supabase queries.

---

## Production Hardening

### Load Test
- Tool: k6 or Locust
- Scenario: 50 concurrent users each uploading a PDF simultaneously
- Pass criteria: P95 upload response < 2s, no pipeline job crashes, Redis memory stable

### RLS Audit
- Every table in Supabase audited: `lesson_jobs`, `lesson_packages`, `quiz_responses`, `teachback_responses`, `session_reports`, `learner_dna`, `lesson_access`, `session_events`
- Audit checklist in `docs/security/rls-audit.md`
- No table left with `ENABLE ROW LEVEL SECURITY` = false (except `profiles` for admin reads)

### Backups
- Supabase daily automated backups enabled (Pro plan)
- Point-in-time recovery window: 7 days
- Railway Redis: AOF persistence enabled

### On-Call Runbook
- Location: `docs/ops/runbook.md`
- Covers: pipeline job stuck, Redis memory full, Stripe webhook failing, Supabase connection pool exhausted

### DPDP Act Compliance (India)
- Privacy policy published at `/privacy`
- Consent checkbox on signup (stored with timestamp)
- Learner DNA data retention policy: deleted on account deletion
- No raw cognitive/emotional scores returned to frontend (Epic 3 constraint)
- Data residency: Supabase region set to `ap-south-1` (Mumbai)

---

## Landing + Pricing Pages

| Page | Route | Key Content |
|---|---|---|
| Landing | `/` | Hero, how it works (3 steps), social proof placeholder, CTA |
| Pricing | `/pricing` | Single tier (Phase 1), per-lesson credit model, FAQ |
| Privacy | `/privacy` | DPDP Act compliant privacy policy |
| Terms | `/terms` | Terms of service |

---

## Technical Scope

| Layer | Files / Modules |
|---|---|
| Auth middleware | `middleware.ts` â€” onboarding gate + route protection |
| Auth routes | `app/auth/` |
| Supabase client | `lib/supabase/client.ts`, `lib/supabase/server.ts` |
| Payments router | `backend/routers/payments.py` |
| Webhook handler | `backend/routers/payments.py::webhook()` |
| Email jobs | `backend/workers/notification_worker.py` |
| Email templates | `backend/notifications/templates/*.html` |
| Admin panel | `app/(admin)/admin/` (route group with layout auth check) |
| Landing pages | `app/page.tsx`, `app/pricing/page.tsx`, `app/privacy/page.tsx` |
| DB migrations | `supabase/migrations/` â€” `lesson_access`, `profiles` (is_admin), `stripe_events` |
| Runbook | `docs/ops/runbook.md` |
| RLS audit | `docs/security/rls-audit.md` |

---

## Out of Scope (Phase 2)

- Subscription / recurring billing (Phase 1 is per-lesson credits)
- Referral or coupon system
- Multi-tenant / institutional accounts
- GDPR compliance (Phase 1 targets India; GDPR deferred)
- SSO / SAML for institutions
- Automated penetration testing

---

## Dependencies

| Dependency | Status |
|---|---|
| Sprint 0 infra + Supabase project | Done |
| Epics 1â€“4 functionally complete (pipeline, player, assessment, tutor) | Must be done before E2E test |
| Stripe account + API keys provisioned | Must be done before Sprint 2 |
| Resend account + domain verified | Must be done before Sprint 3 |
| Legal review of DPDP disclaimer + privacy policy | Must be done before Sprint 4 |
| Supabase Pro plan (for backups) | Must be upgraded before Sprint 4 |

---

## Definition of Done

- [ ] New user can sign up with email, verify, complete onboarding, and land on dashboard
- [ ] Google OAuth sign-in works end-to-end
- [ ] Onboarding gate blocks `/upload` and `/lesson` routes until DNA completed
- [ ] Stripe Checkout session created and student redirected to Stripe-hosted page
- [ ] Successful payment â†’ `lesson_credits` incremented â†’ upload unlocked
- [ ] Stripe webhook signature validation tested with valid and invalid signatures
- [ ] Webhook idempotency tested: duplicate `checkout.session.completed` does not double-credit
- [ ] "Lesson ready" email delivered within 2 minutes of `package_builder` completion
- [ ] Admin panel shows all job statuses, costs, and users (real data, not mocked)
- [ ] Failed job visible in admin panel with error message; retry queues new ARQ job
- [ ] RLS audit completed; checklist signed off; every protected table audited
- [ ] Load test: 50 concurrent users, P95 < 2s, no crashes â€” results documented
- [ ] DPDP consent checkbox on signup with timestamp stored in DB
- [ ] Privacy policy and Terms pages live at `/privacy` and `/terms`
- [ ] On-call runbook covers all 4 critical failure scenarios
- [ ] E2E test: sign up â†’ pay â†’ upload â†’ lesson â†’ report, no developer intervention

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Stripe webhook delivery failure (network, Railway cold start) | Medium | High | Webhook retry in Stripe dashboard; idempotency key prevents double-process |
| RLS misconfiguration exposes user data | Low | Critical | RLS audit checklist before every migration merge; automated test in CI |
| Supabase connection pool exhaustion under 50 concurrent users | Medium | High | Use `pgBouncer` mode on Supabase; pool size tuned in Sprint 4 load test |
| DPDP compliance gap discovered post-launch | Low | High | Legal review in Sprint 3; data deletion flow tested before launch |
| Admin panel accidentally accessible by non-admins | Low | Critical | Server-side `is_admin` check in layout; middleware blocks at edge |
| Email delivery to spam (cold domain) | Medium | Medium | Domain warm-up via Resend; SPF/DKIM/DMARC configured before Sprint 3 |

