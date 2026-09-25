"""Story S5-5 — expand 1-2 topics into enough delivery units to meet the
lesson's MINIMUM narration duration.

Why this exists
---------------
`topic_selection_node` (Story 233) collapses a chapter into 1 topic (T3) or 2
(T1/T2) and overwrites ``state["sections"]``. One topic then became one
delivery unit, so a 45-minute lesson was asked for from two narration calls of
~3,000 words each. A single completion does not produce that: lesson
`d1d6a4e2` delivered 1,672 and 1,363 words (19.3 min of a possible 38.4).

`merge_section_range` is text-preserving, so after `topic_selection` the whole
chapter is still in state, concentrated in 1-2 large bodies. This module cuts
those bodies into the number of delivery units the tier's minimum duration
needs. Nothing new is read.

Two sizes, deliberately distinct (D195)
---------------------------------------
* **Phase-1 window** -- ``settings.section_body_max_chars`` (45,000 since
  Story 233). The most text ONE Phase-1 call is shown. A hard ceiling only.
* **Unit slice size** -- :func:`unit_slice_chars`: ``narration_words_per_segment
  x CHARS_PER_WORD`` (900 x 6.0 = 5,400). The source ONE unit is sized for.

S5-5 as first merged passed the window where the slice size belonged. It had
been written believing the window was 6,000, which Story 233 had already
raised. ``split_body`` returns a body whole when it is under ``max_chars``, so
every topic under 45,000 chars came back as a single unit: the node ran,
checkpointed and logged success while expanding nothing. And a size-driven
slicer cannot honour a count the planner has already decided anyway -- see
:func:`split_into`.

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
    # True when the cap actually SHORTENED the lesson (the duration and the
    # source both wanted more units than `max_segments` allowed). Deliberately
    # independent of `cap_overrun` below: a lesson can be both shortened by the
    # cap AND have exceeded it, because the two describe different halves of
    # the same clamp. An earlier version conflated them and reported
    # `capped=True` while the cap was simultaneously being exceeded.
    capped_by_max_segments: bool = False
    # Units generated BEYOND `max_segments`, forced by the one-unit-per-usable-
    # topic invariant (AC11, which takes precedence over AC15's cap). Always
    # exactly `len(usable) - cap` when it fires, never more — the cap is
    # exceeded by the minimum amount that preserves every topic's text, and by
    # nothing else. 0 in the normal case.
    cap_overrun: int = 0
    # What the cap was, so an overrun is readable from the record without
    # reconstructing config at read time.
    max_segments_configured: int = 0
    # Populated by the node; the pure planner leaves it empty.
    notes: list[str] = field(default_factory=list)


def unit_slice_chars(*, words_per_segment: int, window_chars: int) -> int:
    """Source characters ONE delivery unit is sized for (D195).

    ``words_per_segment x CHARS_PER_WORD``, never above the Phase-1 window --
    a unit bigger than the window would be truncated by the very call it
    feeds. Derived, not configured, so it cannot drift away from the word
    target it represents.
    """
    return max(1, min(int(words_per_segment * CHARS_PER_WORD), window_chars))


def coverage_per_topic(
    topic_lengths: list[int],
    units: list[int],
    *,
    unit_chars: int,
    window_chars: int,
) -> list[int]:
    """How many characters of each topic the lesson's units will carry.

    The lesson carries ``min(total_source, sum(units) x unit_chars)``: exactly
    the source the plan's ``achievable_minutes`` counted on. Carry less and the
    record claims minutes the slices cannot deliver.

    Each topic first gets ``min(length, units x unit_chars)``. Coverage a topic
    cannot use, because it is shorter than its allocation, passes to topics
    that still have text left. Without that hand-off, a small topic beside a
    large one strands its spare allocation: the diagnosed chapter at 127.5 WPM
    claims 45.16 min while per-topic prefixes cover only 42.72.

    No topic is ever given more than ``units x window_chars``: past that a unit
    would exceed what its Phase-1 call is shown. Topics allocated no units get
    zero. Whatever is not covered is the caller's to record (D194).
    """
    caps = [
        min(length, u * window_chars) if u > 0 else 0
        for length, u in zip(topic_lengths, units, strict=True)
    ]
    target = min(sum(caps), sum(max(0, u) for u in units) * unit_chars)
    cover = [min(cap, max(0, u) * unit_chars) for cap, u in zip(caps, units, strict=True)]
    leftover = target - sum(cover)
    for i, cap in enumerate(caps):
        if leftover <= 0:
            break
        take = min(cap - cover[i], leftover)
        cover[i] += take
        leftover -= take
    return cover


# A cut may move off its ideal position by up to this fraction of one slice to
# land on a paragraph break. Beyond that, even unit sizes matter more than
# starting each unit on a fresh paragraph.
_BOUNDARY_SLACK = 0.25


def _nearest_boundary(body: str, lo: int, hi: int, ideal: int) -> int:
    """A cut position in ``[lo, hi]`` near *ideal*: a paragraph break within
    the slack, else the nearest space, else *ideal* itself (clamped)."""
    ideal = min(max(ideal, lo), hi)
    slack = max(1, int((ideal - lo + 1) * _BOUNDARY_SLACK))
    best = -1
    for m in _PARAGRAPH_BREAK.finditer(body, max(lo - 1, 0), min(hi + 2, len(body))):
        cut = m.end()
        if lo <= cut <= hi and abs(cut - ideal) <= slack:
            if best == -1 or abs(cut - ideal) < abs(best - ideal):
                best = cut
    if best != -1:
        return best
    before = body.rfind(" ", lo, ideal)
    after = body.find(" ", ideal, hi)
    candidates = [c + 1 for c in (before, after) if c != -1 and lo <= c + 1 <= hi]
    if candidates:
        return min(candidates, key=lambda c: abs(c - ideal))
    return ideal


def split_into(body: str, units: int, *, max_chars: int) -> list[str]:
    """Cut *body* into EXACTLY *units* contiguous slices (D195).

    ``split_body`` answers "how many pieces of at most N chars?", but by the
    time the node slices, the planner has already decided how many. Deriving
    the count back from a size gets it wrong in both directions on real text:
    a topic smaller than one slice yields one piece where the plan wanted two,
    and paragraph-snapped cuts land short, so a topic that should fill five
    slices yields six and the sixth is dropped.

    Lossless (``"".join(...) == body``) and balanced: each cut aims at an even
    share of what remains, snapped to a nearby paragraph break or space.
    Returns ``min(units, len(body))`` slices (a body cannot be cut into more
    non-empty pieces than it has characters) and ``[]`` for an empty body.
    No slice exceeds *max_chars* provided ``len(body) <= units x max_chars``,
    which :func:`coverage_per_topic` guarantees for the node.
    """
    if not body or units <= 0:
        return []
    count = min(units, len(body))
    n = len(body)
    slices: list[str] = []
    pos = 0
    for remaining in range(count, 1, -1):
        ideal = pos + math.ceil((n - pos) / remaining)
        # Leave at least one character for every slice still to cut.
        hi = min(pos + max(1, max_chars), n - (remaining - 1))
        cut = _nearest_boundary(body, pos + 1, hi, ideal)
        slices.append(body[pos:cut])
        pos = cut
    slices.append(body[pos:])
    return slices


def boundary_at_or_before(body: str, limit: int) -> int:
    """Where to end a covered prefix of at most *limit* chars, preferring a
    paragraph break, then a space, within the last slack-fraction of it."""
    if limit >= len(body):
        return len(body)
    if limit <= 0:
        return 0
    return _nearest_boundary(body, max(1, limit - int(limit * _BOUNDARY_SLACK)), limit, limit)


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
    # Content preservation takes precedence over the fan-out cap (AC11 > AC15).
    #
    #   min(n_wanted, cap)        -- the cap applies as normal, and
    #   max(..., len(usable))     -- is then lifted back ONLY far enough to give
    #                                every usable topic one unit.
    #
    # So the cap is exceeded by exactly `len(usable) - cap` when it would
    # otherwise have dropped a topic, and by nothing else. Without the floor, a
    # chapter with more usable topics than the cap allows silently loses whole
    # topics: slices are cut from one topic's body, so a topic allocated zero
    # units has its text taught nowhere. That is the silent-content-loss class
    # this story exists to remove, and a per-lesson fan-out guard is not worth
    # it — `topic_selection` already bounds topics to 1-2, so the overrun is
    # bounded by the topic count, and `_MAX_PHASE1_SECTIONS` remains the real
    # DoS backstop.
    n_final = max(min(n_wanted, cap), len(usable))
    cap_overrun = max(0, n_final - cap)

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
        # "the cap shortened the lesson", not "the cap was involved".
        capped_by_max_segments=n_wanted > n_final,
        cap_overrun=cap_overrun,
        max_segments_configured=cap,
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
