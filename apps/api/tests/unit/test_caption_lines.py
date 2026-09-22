"""Unit tests for _split_into_caption_lines() — Story 4-29 (BR-6).

Test count: 13 original + 5 from the PR #219 post-merge review (Dev 1)
Coverage:
- AC6a: Multi-sentence script splits at sentence boundaries and distributes
        duration proportionally by character count (not uniformly).
- AC6b: A sentence exceeding max_chars_per_line is split at the last word
        boundary within the limit; no output line exceeds max_chars_per_line chars.
- AC6c: duration_ms=None → returns [], no exception.
- AC6d: Empty script ("") → returns [], no exception.
- AC6e: Single sentence within line limit → one entry spanning [0, duration_ms].
- AC6f: Last line's end_ms equals the input duration_ms exactly (no rounding gap
        even when total doesn't divide evenly across lines).
- Review follow-up (PR #219, Dev 1, addressed in fix/4-29-br6-caption-lines-review-followup):
    - `caption_max_chars_per_line` is a real, wired Settings field, not dead getattr config.
    - A mid-word hard cut (no space within max_chars_per_line) is logged, not silent.
    - No caption line can ever have start_ms == end_ms (zero-width window), even under
      pathological proportional-rounding input.
    - Non-finite duration_ms (NaN/inf) is treated the same as None — [].

All tests are @pytest.mark.unit — pure function, no DB, no Redis, no network.
"""

from __future__ import annotations

import logging

import pytest

from app.modules.content.pipeline.graph import _split_into_caption_lines

# ---------------------------------------------------------------------------
# AC6c — duration_ms=None
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_none_duration_returns_empty_list() -> None:
    """AC6c: None duration → [] — honest empty, not a broken estimate."""
    result = _split_into_caption_lines("This is a sentence. This is another.", duration_ms=None)
    assert result == []


@pytest.mark.unit
def test_none_duration_with_long_script_still_returns_empty() -> None:
    """AC6c: Even a substantive script returns [] when duration is unknown."""
    script = "A " * 200  # 400 chars — well above the line limit
    assert _split_into_caption_lines(script, duration_ms=None) == []


# ---------------------------------------------------------------------------
# AC6d — empty / whitespace-only script
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_script_returns_empty_list() -> None:
    """AC6d: Empty string → []."""
    assert _split_into_caption_lines("", duration_ms=3000) == []


@pytest.mark.unit
def test_whitespace_only_script_returns_empty_list() -> None:
    """AC6d: Whitespace-only string → []."""
    assert _split_into_caption_lines("   \n\t  ", duration_ms=3000) == []


# ---------------------------------------------------------------------------
# AC6e — single sentence within the line limit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_single_short_sentence_produces_one_line() -> None:
    """AC6e: One sentence that fits → exactly one CaptionLine spanning [0, duration_ms]."""
    result = _split_into_caption_lines("Hello, welcome to today's lesson.", duration_ms=2000)
    assert len(result) == 1
    assert result[0]["text"] == "Hello, welcome to today's lesson."
    assert result[0]["start_ms"] == 0
    assert result[0]["end_ms"] == 2000


# ---------------------------------------------------------------------------
# AC6f — last line end_ms equals duration_ms exactly (no rounding gap)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_last_line_end_ms_equals_duration_exactly() -> None:
    """AC6f: Regardless of rounding across intermediate lines, end_ms of the
    last line must equal duration_ms exactly.

    Uses a duration and character split that produces non-integer intermediate
    values to exercise the remainder-to-last-line logic.
    """
    # Three sentences of different lengths so proportional split is non-trivial.
    # duration_ms=1000 chosen so intermediate values are fractional.
    script = "Short. A much longer sentence here. Medium one."
    result = _split_into_caption_lines(script, duration_ms=1000)
    assert len(result) >= 2, "Expected at least 2 lines"
    assert result[-1]["end_ms"] == 1000, (
        f"Last line end_ms was {result[-1]['end_ms']}, expected 1000"
    )


@pytest.mark.unit
def test_last_line_end_ms_prime_duration() -> None:
    """AC6f: Prime duration_ms (1009) guarantees non-trivial remainder."""
    script = "First sentence. Second sentence. Third sentence."
    result = _split_into_caption_lines(script, duration_ms=1009)
    assert result[-1]["end_ms"] == 1009


# ---------------------------------------------------------------------------
# AC6a — multi-sentence proportional distribution (not uniform)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_proportional_not_uniform_distribution() -> None:
    """AC6a: A longer sentence gets a proportionally longer time window than a
    shorter one — distribution is by character count, not equal slices.

    Construct two sentences where one is clearly longer so the test is not
    sensitive to exact floating-point rounding.
    """
    short = "Hi."  # 3 chars
    long_ = "This is a significantly longer sentence that has many more characters."  # 71 chars
    script = f"{short} {long_}"
    result = _split_into_caption_lines(script, duration_ms=7400)

    assert len(result) == 2
    short_duration = result[0]["end_ms"] - result[0]["start_ms"]
    long_duration = result[1]["end_ms"] - result[1]["start_ms"]
    assert long_duration > short_duration, (
        f"Expected longer sentence to get more time: "
        f"short={short_duration}ms long={long_duration}ms"
    )


@pytest.mark.unit
def test_lines_are_contiguous_no_gap() -> None:
    """AC6a: start_ms of each line equals end_ms of the previous — no time gaps."""
    script = "First sentence. Second sentence. Third sentence. Fourth sentence."
    result = _split_into_caption_lines(script, duration_ms=5000)
    assert len(result) >= 2
    for i in range(1, len(result)):
        assert result[i]["start_ms"] == result[i - 1]["end_ms"], (
            f"Gap between line {i - 1} and {i}: "
            f"prev.end={result[i - 1]['end_ms']} cur.start={result[i]['start_ms']}"
        )


@pytest.mark.unit
def test_first_line_starts_at_zero() -> None:
    """AC6a: The first caption line always starts at 0 ms."""
    script = "Welcome. Let us begin. Today we cover photosynthesis."
    result = _split_into_caption_lines(script, duration_ms=4000)
    assert result[0]["start_ms"] == 0


# ---------------------------------------------------------------------------
# AC6b — long sentence split at word boundary, no line exceeds limit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_long_sentence_split_at_word_boundary() -> None:
    """AC6b: A sentence exceeding max_chars_per_line is split at the last space
    within the limit — no mid-word cuts.
    """
    # Build a sentence that is 200 chars — well above the default 120-char limit.
    sentence = "word " * 40  # 200 chars, all complete words
    result = _split_into_caption_lines(sentence.strip(), duration_ms=5000, max_chars_per_line=120)
    for line in result:
        assert len(line["text"]) <= 120, (
            f"Line exceeds 120 chars ({len(line['text'])}): {line['text']!r}"
        )
    # Each line must start with a complete word (no leading/trailing spaces in text)
    for line in result:
        assert line["text"] == line["text"].strip()


@pytest.mark.unit
def test_no_line_exceeds_max_chars_per_line_custom_limit() -> None:
    """AC6b: Respects a custom max_chars_per_line value."""
    script = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda."
    result = _split_into_caption_lines(script, duration_ms=3000, max_chars_per_line=20)
    for line in result:
        assert len(line["text"]) <= 20, (
            f"Line exceeds 20 chars ({len(line['text'])}): {line['text']!r}"
        )


@pytest.mark.unit
def test_output_keys_match_captionline_shape() -> None:
    """Schema contract: every dict in the result has exactly text, start_ms, end_ms."""
    script = "First sentence. Second sentence."
    result = _split_into_caption_lines(script, duration_ms=2000)
    for item in result:
        assert set(item.keys()) == {"text", "start_ms", "end_ms"}, (
            f"Unexpected keys: {set(item.keys())}"
        )
        assert isinstance(item["text"], str)
        assert isinstance(item["start_ms"], int)
        assert isinstance(item["end_ms"], int)


# ---------------------------------------------------------------------------
# PR #219 post-merge review (Dev 1) — 3 confirmed findings addressed in
# fix/4-29-br6-caption-lines-review-followup
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_non_finite_duration_returns_empty_list() -> None:
    """Defence-in-depth, matching `_estimate_slide_timestamps`'s identical
    guard: `_split_into_caption_lines` is a public module symbol other future
    callers could reach directly. NaN/+-inf must be treated the same as
    `None` (explicit []), never reach `round()`."""
    script = "Entropy measures disorder. It only increases over time."
    for bad_value in (float("nan"), float("inf"), float("-inf")):
        assert _split_into_caption_lines(script, duration_ms=bad_value) == [], (
            f"duration_ms={bad_value!r} must return [], not propagate into round()"
        )


@pytest.mark.unit
def test_mid_word_hard_cut_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """CLAUDE.md's silent-truncation rule: a fixed budget (max_chars_per_line)
    meeting variable input (a single token longer than the cap) must not pass
    silently. Matches `duration_ms_by_id`'s own bad-input normalisation,
    which logs rather than silently coercing."""
    overlong_token = "x" * 200  # single unbroken token, no space at all
    with caplog.at_level(logging.WARNING):
        result = _split_into_caption_lines(
            overlong_token,
            duration_ms=5000,
            max_chars_per_line=50,
            lesson_id="lesson-1",
            segment_id="seg-1",
        )
    messages = [r.getMessage() for r in caplog.records]
    assert any("hard-cutting mid-word" in m for m in messages), messages
    assert any("lesson-1" in m and "seg-1" in m for m in messages), (
        "log line should carry the caller-supplied lesson/segment context"
    )
    # The cut still happened correctly despite being forced.
    assert sum(len(line["text"]) for line in result) <= len(overlong_token)


@pytest.mark.unit
def test_no_line_ever_has_zero_width_window() -> None:
    """Round-4 review (Dev 1): a line whose proportional share rounds down to
    0ms must never produce start_ms == end_ms — a window a karaoke-highlight
    consumer keyed on start_ms <= t < end_ms could never activate (the exact
    feature BR-6 exists to unblock). Pathological input: many short lines
    against a tiny total duration, where naive proportional rounding would
    otherwise collapse several lines to zero width."""
    script = " ".join(f"{chr(65 + i)}." for i in range(20))  # "A. B. C. ... T."
    result = _split_into_caption_lines(script, duration_ms=1)
    assert len(result) == 20
    for line in result:
        assert line["end_ms"] > line["start_ms"], f"Zero-width window: {line}"
    # Still contiguous and still ending exactly at (the floored-up) total.
    for i in range(1, len(result)):
        assert result[i]["start_ms"] == result[i - 1]["end_ms"]
