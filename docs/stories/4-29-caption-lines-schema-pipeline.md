---
baseline_commit: "ae1bfaf2f52c31b8a2b50a2e0ad3d24b33e9a1c2"
---

# Story 4-29: Add `caption_lines` to Narration Schema + Server-Side Line-Level Timestamp Estimation

**Status:** in-progress
**Sprint:** Bug Resolution — Feature Sprint 2 (Dev 4 tracker, BR-6 — opportunistic, same pattern as BR-5)
**Branch:** `dev4/master-bug-resolution-br-6-caption-lines` (cut from `main`, PRs directly to `main`)

---

## Story

As Dev 4 (taking on pipeline work with Dev 1's approval — confirmed 2026-09-07),
I want a `caption_lines` field baked into the `Narration` schema and populated by the
`package_builder_node` at lesson-generation time with server-side line-level timestamp
estimates,
so that BR-1 (WebSocket caption-cue delivery) and the forthcoming karaoke-style highlight
feature are unblocked without waiting on a TTS provider that returns word-level timing,
and so the schema shape is already correct for a future values-only swap to real
forced-alignment timestamps (Option 2) with no second frozen-contract PR needed.

---

## Context — decisions already made before this story was written (2026-09-07)

This story closes a gap identified during BR-3/BR-4 triage (the developer's
"BR-3 = caption sync / BR-4 = karaoke" numbering — different from Dev 4's own tracker):

- **Current state:** `NarrationTimestamp` has only slide-level timing (`slide_id`,
  `start_ms`, `end_ms`). Sarvam TTS returns no timing data; both Vexyl TTS and Fish Audio
  TTS also return only audio bytes. There is no per-line, per-word, or per-phrase timing
  anywhere in the pipeline or schema.
- **Decision (confirmed with Dev 2, 2026-09-07):**
  - Line-level is sufficient — no word-level needed for BR-1 or karaoke.
  - Option 1 (server-side estimation) unblocks Dev 2 immediately.
  - Schema shape: new sibling field `caption_lines: CaptionLine[]` on `Narration`,
    NOT nested inside `NarrationTimestamp`. Caption lines don't align 1:1 with slides.
  - Future switch to real forced-alignment values = values-only change, same schema shape.
- **Dev 1 approval:** Dev 4 taking on the pipeline work confirmed 2026-09-07.
- **Vexyl/Fish Audio provider decision:** explicitly out of scope — separate CEO sign-off
  process. This story ships with the existing Sarvam → Azure → Browser fallback chain
  unchanged; `caption_lines` estimates use whatever `duration_ms` `tts_node` already
  measures via `tinytag`.

---

## Acceptance Criteria

- **AC1:** A `CaptionLine` TypeScript interface (`{text: string; start_ms: number;
  end_ms: number}`) is added to `packages/shared/types/lesson.ts` and the `Narration`
  interface gains `caption_lines: CaptionLine[]` (non-optional, empty-array-default —
  consistent with `timestamps: NarrationTimestamp[]` which is also always present).

- **AC2:** The Pydantic mirror (`apps/api/app/schemas/lesson.py`) gains a `CaptionLine`
  model and `Narration.caption_lines: list[CaptionLine] = []` — defaulting to `[]` so
  every existing `Narration` fixture and any already-generated lesson record validates
  without a migration (retroactive-field pattern, same as `tier`/`avatar_intro_url`).

- **AC3:** `packages/shared/lesson_package.schema.json` is updated — `CaptionLine`
  added under `definitions`, `Narration.properties.caption_lines` added as `{type:
  "array", items: {$ref: "#/definitions/CaptionLine"}}`, and `caption_lines` is **not**
  added to `Narration.required` (retroactive-field pattern; matches the
  `avatar_intro_url` precedent). Existing fixture validation must still pass.

- **AC4:** `package_builder_node` in `apps/api/app/modules/content/pipeline/graph.py`
  calls a new `_split_into_caption_lines(script, duration_ms, *, max_chars_per_line)`
  pure function that:
  - Splits `script` into lines at sentence boundaries (`.`, `!`, `?` followed by
    whitespace) first; if a resulting sentence exceeds `max_chars_per_line` (default:
    env var `CAPTION_MAX_CHARS_PER_LINE`, default `120`), splits further at the last
    word boundary within the limit (never mid-word, never silent truncation).
  - Distributes `duration_ms` proportionally across lines by character count:
    `line_start = cursor; line_end = cursor + round(line_chars / total_chars * duration_ms)`.
    Last line receives the remainder so start/end span exactly `duration_ms` with no
    rounding gap.
  - Returns `list[dict]` with keys `text`, `start_ms`, `end_ms` — matching
    `CaptionLine`.

- **AC5:** If `duration_ms` is `None` (browser TTS fallback or `tinytag` failure),
  `_split_into_caption_lines` returns `[]` and `caption_lines` is written as `[]`.
  Estimation without a real audio duration is too imprecise to be useful and would
  silently produce wrong captions — explicit empty is the correct degraded output.

- **AC6:** Unit tests in `apps/api/tests/test_caption_lines.py` prove:
  - **AC6a:** Multi-sentence script splits at sentence boundaries and distributes duration
    proportionally (not uniformly) — a longer sentence gets a proportionally longer window.
  - **AC6b:** A sentence exceeding `max_chars_per_line` is split at the last word boundary
    within the limit; no line ever exceeds `max_chars_per_line` characters.
  - **AC6c:** `duration_ms=None` → returns `[]`, no exception.
  - **AC6d:** Empty script (`""`) → returns `[]`, no exception.
  - **AC6e:** Single sentence that fits within the line limit → returns one entry spanning
    `[0, duration_ms]`.
  - **AC6f:** The last line's `end_ms` equals the input `duration_ms` exactly (no rounding
    gap — verified with a total that doesn't divide evenly across lines).

- **AC7:** The existing `test_package_builder.py` (or equivalent integration fixture)
  still passes after the schema and `package_builder_node` changes — no pre-existing test
  broken by this story. If no such test currently exercises `package_builder_node` with a
  `Narration` output, a `# MOCK-CONTRACT:` comment must be added naming the integration
  path that validates the full assembled `LessonPackage`.

- **AC8:** The 4-dev frozen-contract PR (`packages/shared/types/lesson.ts`,
  `lesson_package.schema.json`, `schemas/lesson.py`) is reviewed and approved by all 4
  developers before the story is marked `[Completed]`. This is the merge gate, not a
  post-merge formality.

---

## Tasks / Subtasks

- [ ] 4-29.1 Create branch, write this story file, push story-first commit alone.
- [ ] 4-29.2 RED phase — write failing tests in `test_caption_lines.py` (AC6a–AC6f)
      before writing `_split_into_caption_lines`. Confirm tests fail for the right reason.
- [ ] 4-29.3 GREEN phase — implement `_split_into_caption_lines()` in `graph.py`; wire
      into `package_builder_node` alongside the existing `_estimate_slide_timestamps` call.
- [ ] 4-29.4 Schema updates (frozen contract):
      - `packages/shared/types/lesson.ts` — `CaptionLine` interface + field on `Narration`
      - `apps/api/app/schemas/lesson.py` — `CaptionLine` model + field on `Narration`
      - `packages/shared/lesson_package.schema.json` — definition + property, not in `required`
- [ ] 4-29.5 Verify AC7 — run existing `package_builder` tests and any Narration fixture
      validation; confirm zero pre-existing failures caused by this story.
- [ ] 4-29.6 Full regression — `apps/api/tests/` unit suite; confirm new tests pass and
      pre-existing failure list is unchanged (document any pre-existing failures by count).
- [ ] 4-29.7 `ruff check --fix && ruff format` on all touched files; confirm clean.
- [ ] 4-29.8 Open PR — request 4-dev frozen-contract review; do not mark `[Completed]`
      until all 4 sign off.
- [ ] 4-29.9 Update `docs/dev4-tracker.md` — add BR-6 entry, mark `[Completed]` after
      merge, update dashboard.

---

## Dev Notes

### Files to change

| File | Change |
|------|--------|
| `packages/shared/types/lesson.ts` | Add `CaptionLine` interface; add `caption_lines: CaptionLine[]` to `Narration` |
| `packages/shared/lesson_package.schema.json` | Add `CaptionLine` definition; add `caption_lines` to `Narration.properties` (NOT `required`) |
| `apps/api/app/schemas/lesson.py` | Add `CaptionLine(BaseModel)`; add `caption_lines: list[CaptionLine] = []` to `Narration` |
| `apps/api/app/modules/content/pipeline/graph.py` | Add `_split_into_caption_lines()`; call from `package_builder_node` |
| `apps/api/tests/test_caption_lines.py` | New — unit tests for `_split_into_caption_lines` (AC6a–AC6f) |
| `docs/dev4-tracker.md` | Add BR-6 entry |

### `_split_into_caption_lines` — implementation sketch

```python
import re

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

def _split_into_caption_lines(
    script: str,
    duration_ms: float | None,
    *,
    max_chars_per_line: int = 120,
) -> list[dict[str, object]]:
    """Split narration script into timed caption lines.

    Returns [] when duration_ms is None or script is empty — explicit empty
    is the correct degraded output; estimation without a real duration is
    silently wrong, not helpfully approximate.
    """
    if not script.strip() or duration_ms is None:
        return []

    # 1. Split at sentence boundaries first.
    sentences = [s.strip() for s in _SENTENCE_END.split(script) if s.strip()]

    # 2. Sub-split sentences that exceed the per-line character cap.
    lines: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars_per_line:
            lines.append(sentence)
        else:
            # Split at last word boundary within the cap — never mid-word.
            remaining = sentence
            while len(remaining) > max_chars_per_line:
                cut = remaining.rfind(" ", 0, max_chars_per_line)
                if cut == -1:
                    cut = max_chars_per_line  # No space found: hard-cut (rare)
                lines.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            if remaining:
                lines.append(remaining)

    if not lines:
        return []

    total_chars = sum(len(l) for l in lines)
    if total_chars == 0:
        return []

    # 3. Distribute duration proportionally by character count.
    result: list[dict[str, object]] = []
    cursor = 0
    for i, line in enumerate(lines):
        if i == len(lines) - 1:
            end = round(duration_ms)  # Last line takes the remainder exactly.
        else:
            end = cursor + round(len(line) / total_chars * duration_ms)
        result.append({"text": line, "start_ms": cursor, "end_ms": end})
        cursor = end

    return result
```

### Frozen-contract retroactive-field pattern (AC2/AC3)

The existing precedent in this codebase for adding a field to an already-deployed schema:
- `tier` on `LessonMetadata`: added as `tier: LessonTier = "T2"` in Pydantic; `tier?` in
  TypeScript; not in `required` in JSON schema → existing records validate without migration.
- `avatar_intro_url` on `LessonPackage`: same pattern (`Optional` + not in `required`).

`caption_lines` follows exactly this pattern. Do **not** add it to `Narration.required` in
the JSON schema — doing so breaks validation of every existing lesson record and fixture.

### `extra="forbid"` on `Narration`

`Narration` has `model_config = _STRICT` (i.e. `extra="forbid"`). Adding `caption_lines`
to the Pydantic model is the correct fix — do not use `model_config = ConfigDict(extra="ignore")`
as a workaround. The field must be declared.

### AC5 rationale — why `None` duration → `[]` not an estimate

The pipeline already has a character-count word-rate estimator (`_estimate_slide_timestamps`
in `graph.py`) for slide timing. That estimator was deliberately **not** reused here:

- Slide timing is used for slide transitions — a few hundred ms of drift is acceptable.
- Caption timing is shown as text to the student — a sentence appearing 5 seconds early
  or late is jarring. Estimated-from-word-count captions without a measured audio anchor
  will consistently drift as narration pace varies.
- The `None` case only fires when the browser TTS fallback is used (no real audio file)
  or `tinytag` failed — both edge cases. `[]` is the honest output; the frontend should
  display static captions (no timing highlight) when `caption_lines` is empty.

---

## Scale & Load (`docs/SCALE-CONTRACT.md` — six questions)

1. **Unit of work and its range.** One `_split_into_caption_lines()` call per segment
   per lesson. Input: `script` (measured range: 1,351–4,069 chars across real segments,
   Story 3-42/3-45). Output: bounded above by `ceil(max_segment_chars / 1)` lines
   (impossible pathological case) and in practice by `ceil(4069 / 1)` = 4,069 lines at
   1 char each — but with `max_chars_per_line=120` and real sentence lengths (avg ~60–80
   chars), a 4,069-char segment yields at most ~51 lines. No line count cap is needed:
   the input is already capped by the existing segment character budget.

2. **Fixed budgets vs. variable input.** `max_chars_per_line` (default 120) is a fixed
   budget against variable sentence length. Behavior beyond it: the sentence is split at
   the last word boundary within the limit — explicit degradation, not silent truncation.
   If no space exists within 120 chars (a single word exceeding the limit — extremely
   rare in educational narration), a hard cut at character 120 is made; this is documented
   in the function docstring and is surfaced by AC6b's test. `duration_ms` is a fixed
   measurement (from `tinytag`) against a variable total — rounding is handled by giving
   the remainder to the last line, so the total span is always exactly `duration_ms` (AC6f).

3. **Scope of limits.** `max_chars_per_line` is a per-call parameter (defaulted from an
   env var); it is per-deployment, not per-user. No per-user state.

4. **Unbounded reads/writes.** None — `_split_into_caption_lines` is a pure function with
   no DB reads, no Redis, no network calls. The output list is written once into the
   assembled `LessonPackage` JSONB by `package_builder_node`, which already writes that
   record in a single bounded operation.

5. **Inherited caps re-derived.** The segment character cap (`narration_max_chars` from
   pipeline config) bounds the maximum script length this function ever receives — it was
   sized for generation, not for caption splitting, and it still applies here without
   re-derivation: the cap limits the generation input, and `_split_into_caption_lines`
   is called on that same script. No new cap is needed.

6. **Check-then-act under concurrency.** N/A — pure function, no shared mutable state,
   no check-then-act sequence. Multiple concurrent pipeline runs each call their own
   independent instance.

---

## Dev Agent Record

### Change Log

- 2026-09-07: Story written (story-first commit). Context: Dev 2 input confirmed,
  Dev 1 approval granted, provider decision (Vexyl/Fish Audio) explicitly deferred.
  Status: in-progress.
