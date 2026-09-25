"""Story S5-5 — expand 1-2 topics into enough delivery units to meet the
lesson's MINIMUM narration duration.

Why this exists
---------------
`topic_selection_node` (Story 233) collapses a chapter into 1 topic (T3) or 2
(T1/T2) and overwrites ``state["sections"]``. Every Phase-1 call then reads at
most ``section_body_max_chars`` (6,000) of one. So the text the generator could
ever see was ``n_topics x 6,000`` — **13.3 min of narration at T1/T2, 6.7 at
T3, regardless of chapter size.** Every tier was structurally short of the
minimum Story S5-4 promises (45/30/15).

The window is not the problem. 900 narration words is 5,400 characters, which
fits inside it comfortably. The problem was reading that window **once per
topic** instead of **once per delivery unit**.

`merge_section_range` is text-preserving, so after `topic_selection` the whole
chapter is still in state — just concentrated in 1-2 large bodies. This module
tiles those bodies into window-sized slices. Nothing new is read, nothing is
dropped, and the 6,000-char window is left exactly as it was.

Deliberately NOT fixed in `coalesce_sections`: that runs in `structure_node`,
and `topic_selection` merges its output back into 1-2 topics immediately
afterwards, so a split there would pass its own unit tests and change nothing
in production. Recorded because the wrong fix is plausible enough to be
proposed again.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Average characters per English word, used only to convert a character count
# into an order-of-magnitude word count. Same constant, same reason, as
# `_SOURCE_CHARS_PER_WORD` in graph.py — coarse by design.
CHARS_PER_WORD = 6.0

# How many narration words one source word can support. 1.0 = narration
# re-expresses the source at roughly its own length. Higher would be asking the
# model to inflate the source, which the anti-fabrication guardrails exist to
# prevent: a chapter that cannot fill the requested time must run SHORT and say
# so, never be padded to hit the clock.
NARRATION_WORDS_PER_SOURCE_WORD = 1.0

# Paragraph separator: a blank line, tolerating trailing spaces and \r\n.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\r?\n")


@dataclass(frozen=True)
class SegmentPlan:
    """How many delivery units this lesson needs, and whether it can have them."""

    segment_count: int
    per_topic_segments: list[int]
    requested_min_minutes: float
    achievable_minutes: float
    content_limited: bool
    capped_by_max_segments: bool = False
    # Populated by the node; the pure planner leaves it empty.
    notes: list[str] = field(default_factory=list)


def split_body(body: str, *, target_chars: int, max_chars: int) -> list[str]:
    """Tile *body* into contiguous slices, none longer than *max_chars*.

    The slices are exact substrings covering the body end to end, so
    ``"".join(split_body(b, ...)) == b`` byte for byte. That is the property
    everything else here depends on: a slicer that loses a character is the
    same defect class as the truncation it replaces, only harder to see.

    Boundaries are chosen in descending order of preference, so a narration
    segment does not begin mid-sentence when it does not have to:

      1. a paragraph break (blank line) at or before *target_chars*;
      2. failing that, a whitespace run — a body with no blank lines at all
         (one long extracted paragraph) still splits between words;
      3. failing that, a hard cut at *max_chars* — a body with no whitespace
         whatsoever (a scanned table, a base64 blob) still has to be split, and
         losing it is not an option.

    Returns ``[]`` for an empty body rather than one blank slice: a blank
    delivery unit would cost an LLM call and ship an empty segment.
    """
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    target = min(max(1, target_chars), max_chars)
    slices: list[str] = []
    pos = 0
    n = len(body)

    while pos < n:
        if n - pos <= max_chars:
            slices.append(body[pos:])
            break

        window_end = pos + max_chars
        cut = -1

        # 1. Last paragraph break that starts at or before the target.
        for m in _PARAGRAPH_BREAK.finditer(body, pos, window_end):
            if m.start() <= pos:  # a break at the very start would not advance
                continue
            if m.end() <= pos + target or cut == -1:
                cut = m.end()
            if m.start() > pos + target:
                break

        # 2. Whitespace fallback — search back from the window edge.
        if cut <= pos:
            probe = body.rfind(" ", pos + 1, window_end)
            if probe > pos:
                cut = probe + 1

        # 3. Hard cut. Never silent — the caller records the fallback.
        if cut <= pos:
            cut = window_end

        slices.append(body[pos:cut])
        pos = cut

    return slices


def plan_segments(
    *,
    topic_bodies: list[str],
    min_narration_minutes: float,
    effective_wpm: float,
    words_per_segment: int,
    max_segments: int,
) -> SegmentPlan:
    """Decide how many delivery units the lesson needs, and how many it can have.

    *min_narration_minutes* is a FLOOR (Story S5-4's amended semantics): more is
    fine, less is only acceptable when the source genuinely cannot support it.

    *effective_wpm* must be the configured primary TTS tier's rate, so the plan
    and the delivered audio are measured against the same assumption — a plan
    built at 150 wpm and spoken at 127.5 misses by ~18% with nothing at fault.

    Three numbers bound the result, in this order:
      * what the tier asks for      (`min_narration_minutes`)
      * what the source can support (total chars -> words at 1:1)
      * what the pipeline will run  (`max_segments`)

    Whichever binds, the reason is on the returned plan rather than inferred
    from the count: `content_limited` and `capped_by_max_segments` are distinct
    because a thin chapter and a capped fan-out want different responses.
    """
    # Indices matter: the caller reads `per_topic_segments[topic_index]` with
    # the ORIGINAL topic index, so the returned list must be the same length
    # and order as `topic_bodies`. An earlier version filtered empty bodies
    # out first, which shifted every later topic's entry and dropped the real
    # content's allocation to the caller's `else 1` fallback — the narration
    # minimum silently defeated, with no error and no log line (PR #255
    # review, finding 1).
    usable = [i for i, b in enumerate(topic_bodies) if b]
    if not usable or words_per_segment <= 0 or effective_wpm <= 0:
        return SegmentPlan(
            segment_count=0,
            per_topic_segments=[0] * len(topic_bodies),
            requested_min_minutes=max(0.0, min_narration_minutes),
            achievable_minutes=0.0,
            content_limited=bool(topic_bodies),
        )

    required_words = max(0.0, min_narration_minutes) * effective_wpm
    n_needed = max(1, math.ceil(required_words / words_per_segment))

    source_words = sum(len(topic_bodies[i]) for i in usable) / CHARS_PER_WORD
    available_words = source_words * NARRATION_WORDS_PER_SOURCE_WORD
    n_possible = max(1, math.ceil(available_words / words_per_segment))

    n_wanted = min(n_needed, n_possible)
    cap = max(1, max_segments)
    # Floor at one unit per usable topic. Without this, a chapter too thin to
    # fill even one slice per topic collapses to a single unit — and because
    # slices are cut from ONE topic's body, every other topic's text is then
    # never taught at all. That is silent content loss, which is the defect
    # class this whole story exists to remove, so the floor takes precedence
    # over the duration arithmetic. Found by the how-to and tier integration
    # tests, not by the unit tests, which is why they exercise the real graph.
    #
    # The operator cap still wins: if `max_segments` is below the topic count,
    # topics genuinely are dropped, and `capped_by_max_segments` records it.
    n_final = min(max(n_wanted, len(usable)), cap)

    # Allocate across the usable topics only, then scatter back onto the
    # original indices. `_allocate` is authoritative for the total: it never
    # returns more than it was given, so the cap holds even when there are
    # more topics than slices (PR #255 review, finding 2).
    allocated = _allocate([topic_bodies[i] for i in usable], n_final)
    per_topic = [0] * len(topic_bodies)
    for slot, topic_index in enumerate(usable):
        per_topic[topic_index] = allocated[slot]
    n_final = sum(per_topic)

    achievable_words = min(n_final * words_per_segment, available_words)
    achievable_minutes = achievable_words / effective_wpm

    return SegmentPlan(
        segment_count=n_final,
        per_topic_segments=per_topic,
        requested_min_minutes=max(0.0, min_narration_minutes),
        achievable_minutes=achievable_minutes,
        content_limited=achievable_minutes + 1e-9 < min_narration_minutes,
        capped_by_max_segments=max(n_wanted, len(usable)) > cap,
    )


def _allocate(bodies: list[str], total: int) -> list[int]:
    """Split *total* slices across *bodies* by length, at least one each.

    Largest-remainder, so the parts sum to exactly *total* — naive rounding
    would drift the lesson's real length away from the plan it was built from.
    """
    k = len(bodies)
    if total <= 0:
        return [0] * k
    if total <= k:
        # Fewer slices than topics. "At least one each" is impossible here, and
        # inventing extra slices would silently breach max_narration_segments —
        # the documented hard cap (PR #255 review, finding 2). Give the one
        # slice to the largest topics and zero to the rest; the shortfall is
        # already reported through content_limited / capped_by_max_segments.
        ranked = sorted(range(k), key=lambda i: len(bodies[i]), reverse=True)
        counts = [0] * k
        for i in ranked[:total]:
            counts[i] = 1
        return counts

    lengths = [float(len(b)) for b in bodies]
    span = sum(lengths)
    spare = total - k
    exact = [(length / span) * spare for length in lengths]
    counts = [1 + int(e) for e in exact]

    leftover = total - sum(counts)
    if leftover > 0:
        order = sorted(range(k), key=lambda i: exact[i] - int(exact[i]), reverse=True)
        for i in order[:leftover]:
            counts[i] += 1
    return counts
