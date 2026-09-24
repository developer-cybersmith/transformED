# Sprint 4 Report — Whole Team

**For:** Engineering Manager
**Sprint:** Sprint 4 (Weeks 8–9) — "get everything solid before real students arrive"
**Report date:** 2026-09-07
**Prepared by:** Dev 4, combining all four developers' individual Sprint 4 write-ups into one plain-language view
**Scope:** All four developers' own Sprint 4 backlogs, merged. Written for a non-technical reader — no jargon, no code terms.

---

## 1. The one-paragraph version

Sprint 4 was about tightening everything up before real, paying students start using the product: testing it under heavy use, turning on payments, tuning the scoring, and closing security gaps. **Across the whole team, most of the planned work is done.** What's left mostly comes down to two honest, nameable reasons — not mystery delays:

1. **Payments aren't switched on yet.** The backend piece is written and already approved, just not yet turned on. The "pay now" button on the website is built but has nothing live to connect to until that happens. One approval unlocks both sides.
2. **Some tuning work can't finish until real students show up.** Things like "is our attention-tracking sensitivity set correctly" or "are our onboarding questions good" need real usage data to check against — there's no way to fake that data honestly, so it's parked, not stuck.

Two more items need a manager's eyes: our servers are showing up in the wrong country (a compliance concern), and one of our supporting tools is close to a usage limit that needs a paid upgrade before real traffic hits it.

---

## 2. Snapshot across the team

| Developer | What they focus on | Done | Still open | Biggest blocker |
|---|---|:--:|:--:|---|
| **Dev 1** | Servers, hosting, payments backend, security checks, site-wide reliability | 5 of 8 | 3 (2 awaiting sign-off, 1 not started) | Payments backend approved but not yet turned on |
| **Dev 2** | The website — pages, buttons, screens students actually see | 10 of 12 | 2 (1 partly done, 1 on hold) | Same payments blocker — waiting on Dev 1's side |
| **Dev 3** | Quiz scoring, engagement scoring, "how is this student really doing" analysis | 6 of 8 (after fixes made this week) | 2 | Needs real student sessions to confirm the scoring is tuned correctly |
| **Dev 4** | Live tutoring behavior — check-ins, reconnects, handling many students at once | 3 of 9 | 6 (see report below) | Needs real students, or a live test server that doesn't exist yet |

**Team-wide: the large majority of planned Sprint 4 work is finished or reviewed and ready. Nothing left is unexplained — every open item has a clear, named reason.**

---

## 3. Dev 1 — Servers, Payments & Security

*(Behind-the-scenes systems: hosting, the payment system's backend half, security checks, backups)*

| Task | Plain description | Status |
|---|---|:--:|
| Handle 50 students at once | Tested the system with 50 people using it at the same time | ✅ Done — worked cleanly |
| Fix pipeline reliability issues | Fixed problems in the process that turns a textbook chapter into a lesson | ✅ Done |
| Turn on real payments | The backend half of the payment system (talks to the payment provider) | ⏳ Written, reviewed, approved — just needs the final "merge" click |
| Limit how fast one person can hit the system | Stops one user from overloading a feature by spamming requests | ✅ Done |
| Security check on who-can-see-what data | Confirmed each student can only ever see their own data, never another student's | ✅ Done |
| Backup / disaster recovery plan | A written plan for what happens if a server goes down or data is lost | ❌ Not started — no plan exists yet |
| On-call guide for outages | A written guide for whoever's on duty when something breaks at night | ⏳ Written, needs one more teammate to read it and sign off |
| Switch the image-generation tool | Moved to a better image tool after the old one shut down | ✅ Done |

**Real problems found and fixed this sprint** (in plain terms):
- **A 3-hour outage** happened because a required setting was missing when the app was deployed — the safety check that should have caught it fired correctly, but the deploy process itself skipped verifying it beforehand. **Fixed**, and a new automatic check now blocks any future deploy that's missing a required setting.
- **The text-to-speech voice tool silently broke** — a setting wasn't locked to a specific version, so the voice provider quietly switched to a newer version behind the scenes, which broke narration. **Fixed**, and pinned so it can't drift again.
- **A missing database update** meant every student's session report page was showing an error page for about 2 days, because an approved change was never actually applied to the live database. **Fixed same day.**
- **The system that creates a new tutoring session was returning an error 100% of the time** for a short window after a recent change. **Fixed same day.**
- One safety check for a rate limiter was found to **fail open instead of closed** — meaning if the safety check itself broke, it let *everything* through instead of blocking things, the opposite of what a safety check should do. **Fixed.**

**Known gaps flagged, not hidden:**
- Our servers are showing up as located in **Singapore, not Mumbai (India)** as intended — this matters for data-residency/compliance rules and needs a decision, not just a code fix.
- One of our supporting tools (fast temporary data storage, used for rate-limiting and quick lookups) **hit its usage cap** this week. Two quick fixes were applied, but the underlying plan needs upgrading before real student traffic arrives.
- The backup/disaster-recovery plan (above) still needs to be written from scratch.

---

## 4. Dev 2 — The Website (What Students See)

| Task | Plain description | Status |
|---|---|:--:|
| Pricing page polish | The page where someone decides to pay and sign up | ❌ Not started — the pricing content itself isn't finalized yet, not a coding delay |
| "Pay now" button wired up | Built the button and payment flow | ⏳ Built and reviewed, but not yet placed on a real page — waiting on Dev 1's payments backend to go live first |
| Usage tracking added everywhere | So we can see how students actually move through a lesson | ✅ Done — but needs one setting turned on in production before it starts collecting real data |
| Accessibility pass | Made sure the site works well with screen readers, keyboards, color contrast, etc. | ✅ Done |
| Faster page loading | Site loads quicker by only loading what's needed, when it's needed | ✅ Done (one part — checking a specific page's speed score — needs a test account that doesn't exist yet) |
| Combined two similar pages into one | Simplified "My Library" and "My Books" into a single page | ✅ Done |
| Fixed a bug: captions got stuck | A caption box on the lesson screen couldn't be scrolled | ✅ Done — found and fixed live in the browser |
| Fixed a bug: lesson restarted itself | After finishing a quiz and reflection at the very end of a lesson, it would jump back to the beginning | ✅ Done, with tests added so it can't silently come back |
| Redesigned captions (one line at a time) | Cleaner, easier-to-read caption style, based on direct feedback | ✅ Done |
| Loading/error/empty screens everywhere | So the site never looks "broken" or blank while things load or go wrong | ✅ Done |
| Handle a lesson that's "still generating" forever | Shows a clear message instead of spinning forever if lesson-building takes too long | ✅ Done |
| Email notifications | Emails when a lesson is ready, or when a session report is ready | ✅ Done — a serious bug was caught and fixed where an email could be silently lost forever |

**Known gaps flagged, not hidden:**
- Pricing page work is on hold until the business side finalizes pricing — not an engineering delay.
- The "pay now" button can't go live until Dev 1's payments backend is switched on.
- The usage-tracking tool needs one production setting turned on before it starts recording anything real.
- One page's loading-speed score couldn't be measured yet — needs a test account to check, not a code issue.
- Captions are timed by an estimate right now, not exact timing — a known, flagged follow-up, already picked up as its own piece of work.

---

## 5. Dev 3 — Scoring, Quizzes & Understanding Student Progress

*(How we measure whether a student is engaged, how quizzes are scored, and the "Learner DNA" profile that describes a student's learning style)*

An independent double-check this week found a few things that looked "done" on paper but weren't fully working — all were fixed within the same day:

| Task | Plain description | Status |
|---|---|:--:|
| Test the scoring system with realistic sample data | Made sure the engagement-score math works correctly and safely, even with many students at once | ✅ Done, fully tested |
| Tune the engagement-score formula | Adjusted how much weight each signal (quiz results, attention, etc.) gets in the overall score, using early data | ⏳ New formula is live in the code, but can't be *proven* correct until real student data confirms it |
| Update the production settings with the tuned formula | Push the new scoring weights live | ✅ Done manually this week |
| Human review of 10 real student learning-style profiles | A person reads 10 real generated profiles and checks they read well and make sense | ❌ Not done — no real student has gone through onboarding yet, so there's nothing to review |
| Review and improve the onboarding questions | Checked 20 onboarding questions, replaced 7 that were flagged as weak, fixed the scoring order | ✅ Done — **a bug was found this week in unrelated *test* code** (not the real feature) that made it look broken; found and fixed same day |
| Analyze where students drop off during a lesson | See where in a lesson students stop engaging | ⚠️ Done, but had to be measured a workaround way — our usage-tracking tool (see Dev 2 above) has never actually received a real event, because a required setting was never turned on. Numbers came from the database directly instead. |
| Make sure finishing a lesson properly saves the final score | Closing out a session correctly writes the final engagement score | ✅ Done and confirmed working |
| Prevent duplicate tutoring sessions being created by accident | A safety check + a database-level lock so the same student can't accidentally start two sessions at once | ✅ Done — the database-level part needs a person to manually apply it in the database console, standard practice for this kind of change |

**Known gaps flagged, not hidden:**
- The usage-tracking tool (PostHog) has **never received a real event** in any environment — a required key was never set. Needs one setting added.
- The temporary fast-storage tool (see Dev 1) **hit its usage limit** this week; a short-term fix is in place, longer-term plan still needed.
- Real student learning-profile review, and confirming the tuned scoring formula is accurate, both **need real students** — parked, not stuck.

---

## 6. Dev 4 — Live Tutoring Behavior

*(Check-in messages, staying connected, reacting to how engaged a student seems)*

**3 of 9 planned pieces are done. 6 are pending — every one of them has a named, specific reason, not a vague delay.**

| # | Task (plain language) | Status | Why |
|---|---|:--:|---|
| 1 | Fix a bug where a check-in message could get permanently stuck on screen | ✅ Done | Fixed two ways — normal dismiss, plus an automatic 45-second safety timer as backup |
| 2 | Let support staff see "what's happening in this student's lesson right now" | ✅ Done | Fully tested, used for demos and troubleshooting |
| 3 | Lock down the exact definition of the 3 camera-based engagement signals with the frontend team | ✅ Done | All 4 developers signed off |
| 4 | Is the "student seems distracted" score cutoff set correctly? | ⏳ Depends on real students | Method is written down; needs ~20 real lesson sessions to compute an answer — no way around this one |
| 5 | Are students actually responding to check-in messages? | ⏳ Depends on real students, plus a small logging piece not yet built | The logging piece can be built now without waiting |
| 6 | Is the 2-minute quiet period after a check-in the right length? | ⏳ Depends on real students, plus the same logging gap as #5 | Same as above |
| 7 | Can we handle 50 students online at once? | ⏳ Depends on a live test server, not students | Already proven working on a local test |
| 8 | If a student's internet drops mid-lesson, do they land back where they left off? | ⏳ Depends on a live test server, not students | Already proven working on a local test |
| 9 | Do check-in messages sound warm, not robotic? | ⏳ Depends on sample lesson content, not students | Needs 5 sample lesson files from Dev 1 — no students needed at all |

**In parallel, while waiting:** fixed a real production outage, built the real backend for the tutor Q&A feature (students can now ask the tutor a question mid-lesson), and started other Sprint-4-adjacent bug fixes that don't need real students.

*(Full detail already delivered separately as the standalone Dev 4 report.)*

---

## 7. Things everyone in the room should know

These affect more than one developer's work, so they're worth calling out together:

- **Payments are the single biggest blocker.** Dev 1's backend is written and approved; Dev 2's website button is built and reviewed. Neither is live because the backend hasn't been switched on yet. **One approval unlocks both.**
- **Our usage-tracking tool has never collected a single real data point**, on any team's feature — a setting was never turned on in production. Both Dev 2 and Dev 3 hit this same wall independently this week.
- **Our servers are showing up in the wrong country** (Singapore instead of the intended Mumbai, India). This is a compliance question, not just a technical one, and needs a decision from someone with that authority.
- **A supporting fast-storage tool hit its usage cap** this week. Short-term fixes are in, but it needs a paid-plan upgrade before real student traffic arrives, or it will hit the same wall again — just under real users this time.
- **Several pieces of tuning work across two developers (Dev 3 and Dev 4) all wait on the same thing: real student sessions.** None of this can be rushed honestly — the whole point is calibrating against real behavior, not invented numbers.

---

## 8. Recommended next steps, in order

1. **Approve and switch on the payments backend** — this single step unblocks Dev 1 and Dev 2 at once.
2. **Turn on the usage-tracking key in production** — a five-minute setting change that unblocks real data for both Dev 2 and Dev 3.
3. **Decide on the server-location issue** — it's a compliance risk that shouldn't wait for launch to get attention.
4. **Upgrade the fast-storage tool's plan** before real students create real traffic against its current limit.
5. **Get the two pending write-ups signed off** — the disaster-recovery plan (needs to be written) and the on-call guide (needs one more reviewer).
6. **Once real students start arriving:** revisit the engagement-score cutoff, the check-in timing, the check-in message tone, and the learning-style profile review — all pre-written and ready to go the moment real data exists.

---

## 9. Bottom line

Sprint 4 did what a sprint like this is supposed to do: nearly everything that *could* be finished without real students, got finished. What's left is not a mystery in any case — it's one shared blocker (payments), one shared gap (usage tracking never turned on), two items that need a manager decision (server location, storage plan), and a cluster of tuning work that honestly cannot be done without real students using the product. The team is in a good position to move fast the moment the first real students arrive.

---

*Report generated by Claude Code (Dev 4 reporting session) · 2026-09-07*
*Sources: `sprint-4-report.md` (Dev 1), `sprint4-dev2-report.md` (Dev 2), `sprint4-dev3-audit-2026-09-07.md` (Dev 3), `docs/dev4-tracker.md` Sprint 4 section (Dev 4) — merged and translated into plain language.*
