# Book-scale — status

> ## ⛔ SUPERSEDED — read `docs/book-scale-phase-tracker.md` first
>
> Since this was written (2026-08-04): Phase 6.5 and Track W W3/W4 landed, book-scale **merged
> to `main`** (`b199537`, revert tag `pre-book-scale-2026-08-05`), and Phase 7's acceptance run
> was attempted on 2026-08-05 and **blocked at the first paid call — $0.00 spent, OpenAI
> balance is zero**. The tracker's START HERE block has the resume steps. Everything below is
> the 2026-08-04 snapshot and is kept for history only.

# Book-scale — status, 2026-08-04

**Owner:** Dev 1 · **Branches:** `book-scale/integration`, `book-scale/phase-6-endpoints`, `book-scale/track-w`
**Authoritative detail:** `docs/book-scale-phase-tracker.md` · `docs/DEFECT-REGISTER.md`

The one success criterion: *upload a 1,000-page PDF and have Sprint 1 + Sprint 2 run to
completion without failing.* Sprint 3 starts after Phase 7 verifies.

---

## Where we are

| Phase | Status |
|:--|:--|
| 1 · Prove chapter detection | ✅ Verified |
| 2 · Make chapters storable | ✅ Verified |
| 3 · Detect + store chapters at upload | ✅ Verified |
| 3.5 · Books/chapters readable | ✅ Verified |
| 4 · Extract one chapter's pages | ✅ Verified |
| 5 · Chapter-scoped generation | 🧪 Implemented |
| 6 · Endpoints (the write endpoint) | 🧪 Implemented |
| 6.5 · `lesson_ready` reaches a client | ⬜ Not started |
| 7 · Prove it end to end + merge to `main` | ⬜ Not started |

**Track W (frontend):** W1 done · W0, W2 in progress · W3, W4 not started.

Phases 5 and 6 are `Implemented`, not `Verified`, because both need one paid generation run.
That run happens **once**, in Phase 7 (decision **D43**). Phase 6 was briefly marked Verified on
2026-08-04; the review caught that its own exit tests items 3–4 (*"lesson generates"*) had never
been run, and it was downgraded rather than have the criteria rewritten to match the result.

---

## What is proven, with numbers

Live against the real 1,151-page book and the real Supabase project:

| | |
|:--|:--|
| Ingest | 1,151 pages → **21 chapters**, 90.3 s end to end |
| Generation endpoint | **12/12** — create 202, idempotent 200, second tier, four negatives |
| Page bounds → subprocess | **3/3** — argv `(40, 68)`, images only on pages 52/54/55/61 |
| **The premise** | **82,665 chars for a 29-page chapter** vs **~3,280,945** for the whole book |
| Gating suite | **1068 passed, 1 skipped** (was 968 / 10) |
| Largest real chapter | **98 pages**, against a 200-page cap — nothing legitimate is refused |

---

## What the 5-agent review found (3 of 5 layers reported)

| ID | Finding | State |
|:--|:--|:--|
| **D52** | Rate limiter keyed by **IP, not user** — every authenticated caller shared one bucket, so one user could lock out everyone behind the same egress IP. Predates Phase 6. | Fixed, 8 tests |
| **D53** | A lesson stuck in `generating` is permanent — no age bound, nothing clears it. Three of them lock a user out of generation forever. | Registered, fix pending |
| **D54** | No way to regenerate a lesson. Previously a subordinate clause in an unrelated defect. | Registered |
| — | **No CI ran on any book-scale branch.** `pull_request` triggered on `main` only; every branch merges to `book-scale/integration`. Six phases merged with zero checks. | Fixed (W0 AC8) |
| — | `D52` was cited by ID in three files, including a load-bearing code comment, **before its register row existed**. | Fixed |
| — | A live mutation (`lessons!chapters_lesson_id_fkey`) was left in production code by a review agent. Returns HTTP 200 and silently breaks the feature. | Reverted |

Also fixed: D51 closed, tracker self-contradictions, CI guard tightened to an exact count,
PostgREST image pinned, contract provenance restored, two wrong numbers in the story.

---

## Remaining

1. **`router.py` fixes** — UUID canonicalisation (uppercase UUIDs currently 404 on resources you
   own), the concurrency check-then-act race, D53's staleness bound, scoping the embed to the
   caller. *Held until the Test Coverage layer stops mutating that file.*
2. **Review layers 3 and 4** to report, then their fixes.
3. **W0, W2** to land → then **W3** (tier moves to the chapter card) and **W4** (MSW off).
4. **Phase 6.5** — the `lesson_ready` push (D34).
5. **Phase 7** — acceptance run + the single merge to `main`. This run also discharges Story 1-13
   AC10 and is what turns Phases 5 and 6 into ✅ Verified.

---

## The recurring lesson

Every defect this effort has found is the same shape: **something reported success without being
checked.** The CI anti-vacuum guard that only matched an all-skipped run. The rate-limit fallback
logged at DEBUG. A stale uvicorn serving 3 routes while source had 4. My own port check written
with a regex that could never match. Two stale ARQ workers failing every lesson. And CI itself,
never running at all.

None of it was found by unit tests. All of it was found by running the real thing and looking.
