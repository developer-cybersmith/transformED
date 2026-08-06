---
failed_layers: '' # set at runtime: comma-separated list of layers that failed or returned empty
---

# Step 2: Review

## RULES

- YOU MUST ALWAYS SPEAK OUTPUT in your Agent communication style with the config `{communication_language}`
- The Blind Hunter subagent receives NO project context — diff only.
- The Edge Case Hunter subagent receives diff and project read access.
- The Acceptance Auditor subagent receives diff, spec, and context docs.
- The Scale & Load Hunter subagent receives diff and project read access.
- All review subagents must run at the same model capability as the current session.
- **The Scale & Load Hunter is mandatory and is never skipped.** It runs in both `"full"` and
  `"no-spec"` modes. It is the only layer with no skip condition: the failure it hunts —
  `docs/SCALE-CONTRACT.md` "a system that **reported success while being wrong**" — is invisible
  to every other layer, because nothing errors and no acceptance criterion is violated.

## INSTRUCTIONS

1. If `{review_mode}` = `"no-spec"`, note to the user: "Acceptance Auditor skipped — no spec file provided."

2. Launch parallel subagents without conversation context. If subagents are not available, generate prompt files in `{implementation_artifacts}` — one per reviewer role below — and HALT. Ask the user to run each in a separate session (ideally a different LLM) and paste back the findings. When findings are pasted, resume from this point and proceed to step 3.

   - **Blind Hunter** — receives `{diff_output}` only. No spec, no context docs, no project access. Invoke via the `bmad-review-adversarial-general` skill.

   - **Edge Case Hunter** — receives `{diff_output}` and read access to the project. Invoke via the `bmad-review-edge-case-hunter` skill.

   - **Acceptance Auditor** (only if `{review_mode}` = `"full"`) — receives `{diff_output}`, the content of the file at `{spec_file}`, and any loaded context docs. Its prompt:
     > You are an Acceptance Auditor. Review this diff against the spec and context docs. Check for: violations of acceptance criteria, deviations from spec intent, missing implementation of specified behavior, contradictions between spec constraints and actual code. Output findings as a Markdown list. Each finding: one-line title, which AC/constraint it violates, and evidence from the diff.

   - **Scale & Load Hunter** (always — never skipped, in either `{review_mode}`) — receives
     `{diff_output}` and read access to the project. Before writing its prompt, load
     `{project-root}/docs/SCALE-CONTRACT.md` and pass it verbatim as part of the prompt. Its prompt:
     > You are the Scale & Load Hunter. You are the only reviewer whose job is the failure that
     > does not error. This codebase's signature defect is not slowness — it is, quoting
     > `docs/SCALE-CONTRACT.md`: "A 1,000-page textbook uploaded fine, processed fine, and produced
     > a lesson. The lesson covered **4 % of the book**. Nothing errored. Nothing warned. The
     > `$3.00/lesson` cost ceiling never fired, because the failure was *cheap*, not expensive."
     >
     > Audit this diff against the six questions of the scale contract, in this order. Read the
     > surrounding source, the callers, and `supabase/migrations/` as needed — the diff alone will
     > not show you the caps a changed line inherits.
     >
     > 1. **Unit of work.** What is ONE unit here, and what is its range — min, typical, largest
     >    actually measured, and what happens beyond it? Flag any place the unit is implicitly "one
     >    PDF" where it should be "one chapter" (the original defect: a 1,151-page book became one
     >    lesson from 90,000 characters).
     > 2. **Fixed budget meeting variable input.** Enumerate every fixed cap in the diff that meets
     >    a variable input: token windows, section counts, character limits, page counts, byte
     >    sizes, timeouts, retry counts, array slices, `[:n]`, `max_*`, `LIMIT n`. For each, state
     >    what happens past the limit. **A finding is CONFIRMED whenever the answer is silent
     >    truncation** — including truncation that only emits a `logger.warning`. Compare
     >    `structure_max_sections = 15` × `_get_section_body(max_chars=6000)`: ~90,000 chars is the
     >    entire LLM-visible window regardless of input size, ~36 pages at 2,500 chars/page. An
     >    explicit error or an explicitly surfaced degradation is acceptable; a warning line in a
     >    log nobody reads is not.
     > 3. **Ambiguous limit scope.** For every limit, rate, quota, counter, cache and lock: is its
     >    scope per-user, per-instance, or per-deployment — and is that stated? Unstated scope is a
     >    finding. Precedents: **D52**, the rate limiter fell back to keying by IP, so every
     >    authenticated user shared one bucket and one caller could lock out everyone behind the
     >    same egress IP; **D49**, `RATE_LIMIT_STORAGE_URL` defaults to `memory://`, so every
     >    ceiling silently multiplies by replica count.
     > 4. **Unbounded reads and writes.** Every query reachable from a request path must carry a
     >    `.limit()` / `.range()`, use an exact count instead of materialising rows, or carry a
     >    written `# BOUNDED:` justification for why the row count is naturally bounded. No
     >    justification = finding. Precedents: the per-user concurrency gate did
     >    `select("lesson_id")` over every `generating` row just to count them; the chapters→lessons
     >    embed had no limit, so a chapter regenerated 20 times returned 20 rows to every
     >    chapter-list request; **D50**, 300-DPI page rendering and image upload had no count cap at
     >    all and sat entirely outside `cost_tracker`.
     > 5. **Inherited caps.** Which caps in or around this diff were sized against a superseded unit
     >    of work and never re-derived? Show the arithmetic that is now wrong. Precedent: the 50 MB
     >    upload cap was sized when one upload was one lesson, and was never revisited when the unit
     >    became a book — so OpenStax Physics (1,671 pages, 251 MB) and Biology (1,475 pages, 382 MB)
     >    cannot be ingested at all, though chapter detection handles them perfectly.
     > 6. **Check-then-act under concurrency.** For every read-then-write with no lock, transaction
     >    or UNIQUE constraint between them: what happens when N requests arrive simultaneously, and
     >    how much damage is bounded? Precedents: the per-user concurrency cap counts `generating`
     >    lessons and then inserts with nothing in between, so three concurrent requests all see the
     >    same count and all insert; **D45**, the `(chapter_id, tier)` idempotency pre-check has the
     >    same shape with no UNIQUE constraint to fall back on, so concurrent duplicates both bill.
     >
     > Then answer the contract's one-line test, which outranks all six:
     > **"What input makes this silently wrong rather than loudly broken?"** Every input you can
     > name that produces a success response containing a wrong result is a finding, whether or not
     > it fits questions 1–6. Prefer these findings over all others and list them first.
     >
     > **Reporting rules — findings that break these are discarded, not downgraded:**
     > - Every finding MUST name a concrete triggering input with a magnitude: a page count, a row
     >   count, a byte size, a character count, a replica count, a request rate, a number of
     >   concurrent callers. "A large book" is not a finding; "a 1,151-page book (~2.9 M chars)" is.
     > - Every finding MUST state the observable wrong outcome and whether the system errors, warns,
     >   or reports success. Say which.
     > - NEVER write "this might not scale", "consider performance", "could be slow", or any
     >   finding whose evidence is an adjective. If you cannot compute the number at which it
     >   breaks, you do not have a finding.
     > - Slowness alone is not a finding unless it crosses a stated timeout or budget. Wrongness
     >   reported as success always is.
     >
     > Output findings as a JSON array. Each object: `location` (file:line), `contract_question`
     > (1–6, or `one-line-test`), `triggering_input` (with the magnitude), `observed_behaviour`
     > (one of `silent-truncation`, `silent-wrong-result`, `explicit-error`, `unbounded-growth`,
     > `scope-ambiguous`, `race`), `consequence`, and `evidence` (the code or cap that proves it).
     > If you find nothing, return `[]` — do not pad with generic performance advice.

3. **Subagent failure handling**: If any subagent fails, times out, or returns empty results, append the layer name to `{failed_layers}` (comma-separated) and proceed with findings from the remaining layers.

4. Collect all findings from the completed layers.

5. **Scale gate.** If the Scale & Load Hunter is in `{failed_layers}` — failed, timed out, or
   returned nothing at all (a genuine clean result is the literal `[]`, which is not empty output)
   — the review is NOT complete. Say so explicitly to the user in step 3's failed-layer report and
   never allow a "✅ Clean review" announcement while it is listed. Re-run it once before giving up.


## NEXT

Read fully and follow `./step-03-triage.md`
