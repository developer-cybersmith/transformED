---
---

# Step 3: Triage

## RULES

- YOU MUST ALWAYS SPEAK OUTPUT in your Agent communication style with the config `{communication_language}`
- Be precise. When uncertain between categories, prefer the more conservative classification.

## INSTRUCTIONS

1. **Normalize** findings into a common format. Expected input formats:
   - Adversarial (Blind Hunter): markdown list of descriptions
   - Edge Case Hunter: JSON array with `location`, `trigger_condition`, `guard_snippet`, `potential_consequence` fields
   - Acceptance Auditor: markdown list with title, AC/constraint reference, and evidence
   - Scale & Load Hunter: JSON array with `location`, `contract_question`, `triggering_input`,
     `observed_behaviour`, `consequence`, `evidence` fields

   If a layer's output does not match its expected format, attempt best-effort parsing. Note any parsing issues for the user.

   Convert all to a unified list where each finding has:
   - `id` -- sequential integer
   - `source` -- `blind`, `edge`, `auditor`, `scale`, or merged sources (e.g., `blind+edge`)
   - `title` -- one-line summary
   - `detail` -- full description
   - `location` -- file and line reference (if available)

   For `scale` findings, `detail` MUST retain the `triggering_input` magnitude and the
   `observed_behaviour` verbatim. A scale finding stripped of its number is unverifiable and
   becomes indistinguishable from the "consider performance" advice the layer is forbidden to emit.

2. **Deduplicate.** If two or more findings describe the same issue, merge them into one:
   - Use the most specific finding as the base (prefer edge-case JSON with location over adversarial prose).
   - Append any unique detail, reasoning, or location references from the other finding(s) into the surviving `detail` field.
   - Set `source` to the merged sources (e.g., `blind+edge`).

3. **Classify** each finding into exactly one bucket:
   - **decision_needed** -- There is an ambiguous choice that requires human input. The code cannot be correctly patched without knowing the user's intent. Only possible if `{review_mode}` = `"full"`.
   - **patch** -- Code issue that is fixable without human input. The correct fix is unambiguous.
   - **defer** -- Pre-existing issue not caused by the current change. Real but not actionable now.
   - **dismiss** -- Noise, false positive, or handled elsewhere.

   If `{review_mode}` = `"no-spec"` and a finding would otherwise be `decision_needed`, reclassify it as `patch` (if the fix is unambiguous) or `defer` (if not).

   **Scale findings carry two extra classification rules — they are not discretionary:**
   - A `scale` finding whose `observed_behaviour` is `silent-truncation` or `silent-wrong-result`
     may NEVER be classified `dismiss`. Per `docs/SCALE-CONTRACT.md` §2, "Silent truncation is
     never an acceptable answer" — the whole point is that this class of defect looks like a false
     positive because nothing errors. Classify it `patch` or `decision_needed`. If you believe it
     is genuinely a false positive, say so to the user and let them decide; do not drop it silently.
     Dropping it silently is the failure being reviewed for.
   - A `scale` finding classified `defer` must be given a `D-nn` register ID in
     `docs/DEFECT-REGISTER.md`, with an owner and a trigger, per register binding rule 8 and rule 5
     ("A documented limitation is NOT an accepted one"). A deferred scale finding with no `D-nn` is
     not deferred — reclassify it `patch`.

4. **Drop** all `dismiss` findings. Record the dismiss count for the summary.

5. If `{failed_layers}` is non-empty, report which layers failed before announcing results. If
   `Scale & Load Hunter` is among them, state plainly that scale was NOT reviewed on this change
   and that the review does not satisfy the review gate — never announce a clean review. If zero findings remain after dropping dismissed AND `{failed_layers}` is non-empty, warn the user that the review may be incomplete rather than announcing a clean review.

6. If zero findings remain after triage (all rejected or none raised): state "✅ Clean review — all layers passed." (Step 3 already warned if any review layers failed via `{failed_layers}`.)


## NEXT

Read fully and follow `./step-04-present.md`
