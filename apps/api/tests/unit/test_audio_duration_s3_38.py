"""
Unit tests for Story 3-38: tts_node measures REAL audio duration via tinytag,
instead of package_builder_node always guessing it from word_count/words_per_minute.

Covers docs/stories/3-38-real-audio-duration.md's ACs:
- AC 2/AC 3: tts_node measures a real duration_ms from synthesized audio bytes
  on success; a tinytag parse failure degrades to duration_ms=None, never
  crashes the node.
- AC 4: duration_ms is a SIBLING key to "data" on the audio_assets wrapper
  dict, on every path (success / browser-fallback / whole-segment exception).
- AC 6/AC 7/AC 8: package_builder_node passes the real duration through to
  `_estimate_slide_timestamps` via `known_duration_ms`, which uses it directly
  instead of the word-count estimate; the estimate path is unchanged when
  `known_duration_ms` is None.

Round 2 review note: this story originally shipped with `mutagen`, mislabeled
MIT in the ACs/pyproject comment — `mutagen` is actually GPL-2.0-or-later
(verified via `pip show mutagen` / its own `COPYING` file, not asserted from
memory). Swapped to `tinytag` (genuinely MIT, same way of verifying),
consistent with this codebase's zero-copyleft-dependency pattern (PyMuPDF
banned by name for AGPL-3.0; every PDF library hand-picked for a verified
permissive license). `tinytag` computes MP3 duration from the frame count
(samples-per-frame / sample-rate) rather than `mutagen`'s byte-count/bitrate
method, so the fixture's measured duration is ~2612ms here, not the
mutagen-era ~2606ms — both are legitimate MP3 duration estimates for the same
bytes; the two libraries simply use different (both standard) methods.

A NOTE ON THE FIXTURE: this project's DEFECT-REGISTER.md explicitly calls out
mock-shaped tests as a real, historical problem ("b'AUDIO_BYTES' is not
audio"). `test_tts_node.py`'s existing fixtures (b"AUDIO_BYTES", b"AZURE_AUDIO")
are NOT valid MP3 — tinytag cannot parse them, so they are useless for testing
duration MEASUREMENT (they are fine for the pre-existing tests, which never
assert on duration). The tests below build a genuine, tinytag-parseable MP3
instead of reusing those fixtures for anything duration-related.

HOW THE FIXTURE IS BUILT: a single, hand-built minimal MPEG-1 Layer III audio
frame, repeated N times (each additional copy adds one frame's worth of real,
tinytag-computed duration — no ffmpeg, no encoder library, just the raw MPEG
frame format):
  - Bytes 0-1: 0xFF 0xFB — sync word (11 ones) + MPEG version=MPEG-1 (11) +
    layer=Layer III (01) + protection_bit=1 (no 16-bit CRC follows).
  - Byte 2: 0x90 — bitrate_index=1001 (128 kbps, MPEG-1/Layer III table) +
    sampling_rate_index=00 (44100 Hz) + padding=0 + private=0.
  - Byte 3: 0x04 — channel_mode=00 (stereo) + mode_extension=00 +
    copyright=0 + original=1 + emphasis=00.
  - The rest of the frame is zero-filled "silent" payload, sized to the
    standard MPEG-1/Layer III frame-length formula:
    `frame_len = 144 * bitrate / sample_rate` (= 417 bytes at 128kbps/44100Hz,
    truncated to 417 by integer division — `(144 * 128_000) // 44_100 == 417`,
    matches the format spec. Round 1 mistakenly wrote 470 here — corrected in
    Round 2 review; the code always computed the number, it was only this
    comment's own arithmetic that was wrong).
  Verified directly against `tinytag.TinyTag` before writing any assertion
  below that depends on it (see `test_fixture_is_genuinely_parseable_by_tinytag`).
"""

from __future__ import annotations

import io
import json
import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tinytag import TinyTag

FAKE_LESSON_ID = "31313131-3131-3131-3131-313131313131"


def _build_real_mp3(n_frames: int) -> bytes:
    """Hand-built minimal MPEG-1 Layer III frame(s) — see module docstring
    for the exact byte-level construction. Real enough for `tinytag` to
    report a genuine, non-zero duration, which is all these tests need."""
    header = bytes([0xFF, 0xFB, 0x90, 0x04])
    bitrate = 128_000
    sample_rate = 44_100
    frame_len = (144 * bitrate) // sample_rate  # 417 bytes/frame at this bitrate/rate
    frame = header + b"\x00" * (frame_len - len(header))
    return frame * n_frames


# A ~2.6-second fixture (100 frames) — long enough that tinytag's measured
# duration is unmistakably different from any word-count estimate a 3-6 word
# test script would produce at the default 150 wpm setting (~1000-1400ms).
REAL_MP3_BYTES = _build_real_mp3(100)


def _real_mp3_duration_ms(data: bytes = REAL_MP3_BYTES) -> int:
    """The SAME computation tts_node performs — used by most tests below to
    assert against tinytag's own real, measured value, not a hand-guessed
    constant that could drift from tinytag's actual rounding/frame-table
    behavior. See `test_fixture_duration_matches_a_pinned_independently_
    computed_value` (Round 2 review) for a companion assertion pinned to a
    literal instead, so a bug that changed this exact formula in both this
    helper and production simultaneously would still be caught by something."""
    tag = TinyTag.get(file_obj=io.BytesIO(data))
    assert tag.duration is not None
    return round(tag.duration * 1000)


def test_fixture_is_genuinely_parseable_by_tinytag() -> None:
    """Sanity check on the fixture ITSELF, independent of tts_node/
    package_builder_node — proves the hand-built bytes are real, parseable
    MP3 with a non-zero duration before any test below relies on that."""
    tag = TinyTag.get(file_obj=io.BytesIO(REAL_MP3_BYTES))
    assert tag.duration is not None
    duration_ms = round(tag.duration * 1000)
    assert duration_ms > 2000, "100 frames at 44100Hz should be a couple of seconds"


def test_fixture_duration_matches_a_pinned_independently_computed_value() -> None:
    """Round 2 review finding (Blind Hunter): `_real_mp3_duration_ms()` uses
    the exact same `round(tag.duration * 1000)` formula tts_node itself runs,
    so a test that ONLY ever compares against that helper could theoretically
    not catch a bug that changed the rounding/unit-conversion formula
    identically in both places at once. Pin an independently-observed literal
    here too: confirmed by actually running this exact fixture through
    tinytag (see this story's Round 2 Senior Developer Review section) — NOT
    hand-derived from the MPEG frame-length formula on paper, since tinytag's
    duration algorithm (frame-count x samples-per-frame / sample-rate) is an
    implementation detail of the library, not something this test should
    re-derive independently and risk drifting from tinytag's actual output."""
    assert _real_mp3_duration_ms() == 2612


# ---------------------------------------------------------------------------
# tts_node: measuring the real duration
# ---------------------------------------------------------------------------


def _mock_tts_supabase(node_outputs: dict[str, Any] | None = None) -> MagicMock:
    sb = MagicMock()
    jobs_mock = MagicMock()
    jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs or {}
    }
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    sb.table.return_value = jobs_mock
    sb.storage.from_.return_value.upload.return_value = MagicMock()
    return sb


def _tts_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "narration_scripts": [
            {
                "segment_id": "sec_0",
                "script": "Entropy measures disorder in a system.",
                "narration_style": "conversational",
                "word_count": 6,
            }
        ],
        "progress_pct": 48.0,
        "error": None,
    }
    state.update(overrides)
    return state


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_synthesis_measures_real_duration_via_tinytag() -> None:
    """AC 2/AC 4: a real MP3 buffer from the TTS provider is measured via
    tinytag, and the result is carried as a SIBLING "duration_ms" key next to
    "data" — not inside it (Narration is extra='forbid', frozen schema).

    This is the RED-defining test for AC 2/AC 4: pre-fix, "duration_ms" is
    entirely absent from the wrapper dict (tts_node never computed it), so
    `assets[0]["duration_ms"]` raises KeyError against the unfixed code.
    """
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (REAL_MP3_BYTES, [])
    sb = _mock_tts_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_tts_state())

    assets = result["audio_assets"]
    assert len(assets) == 1
    assert assets[0]["segment_id"] == "sec_0"
    # "data" is still exactly the frozen Narration shape — duration_ms must
    # NOT be inside it.
    assert "duration_ms" not in assets[0]["data"]
    assert set(assets[0]["data"]) == {"script", "audio_url", "audio_provider", "timestamps"}
    # The sibling key carries the REAL measured value — not a placeholder,
    # not the estimate a word-count formula would produce.
    assert assets[0]["duration_ms"] == _real_mp3_duration_ms()
    assert assets[0]["duration_ms"] > 2000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tinytag_parse_failure_degrades_duration_to_none_not_crash() -> None:
    """AC 3: a provider returning bytes tinytag cannot parse (corrupt/non-MP3)
    must NOT crash tts_node — duration_ms degrades to None, the rest of the
    segment (audio upload, Narration) still succeeds normally."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    # Not valid MP3 at all — this is deliberately the "b'AUDIO_BYTES' is not
    # audio" shape DEFECT-REGISTER.md warns about, used HERE specifically to
    # prove the parse-failure path, not to claim duration measurement works.
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_tts_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_tts_state())

    assets = result["audio_assets"]
    assert assets[0]["duration_ms"] is None
    # The rest of the segment must be unaffected by the parse failure.
    assert assets[0]["data"]["audio_provider"] == "sarvam"
    assert assets[0]["data"]["audio_url"] == f"{FAKE_LESSON_ID}/sec_0.mp3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_fallback_has_duration_none() -> None:
    """AC 4: the browser-fallback path (no server audio synthesized at all)
    must carry duration_ms=None — there is no audio to measure."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.side_effect = RuntimeError("Sarvam down")
    mock_azure = AsyncMock()
    mock_azure.synthesize.side_effect = RuntimeError("Azure down")
    sb = _mock_tts_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.providers.tts.azure.AzureTTSProvider", return_value=mock_azure),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_tts_state())

    assets = result["audio_assets"]
    assert assets[0]["data"]["audio_provider"] == "browser"
    assert assets[0]["duration_ms"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_whole_segment_exception_path_has_duration_none() -> None:
    """AC 4: the whole-segment except branch (malformed entry, e.g. missing
    'script') must also carry duration_ms=None on its wrapper dict."""
    from app.modules.content.pipeline.graph import tts_node

    sb = _mock_tts_supabase()
    malformed = {"segment_id": "sec_bad"}  # missing "script" -> KeyError inside try

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await tts_node(_tts_state(narration_scripts=[malformed]))

    assets = result["audio_assets"]
    assert assets[0]["data"]["audio_provider"] == "browser"
    assert assets[0]["duration_ms"] is None


# ---------------------------------------------------------------------------
# _estimate_slide_timestamps: known_duration_ms keyword
# ---------------------------------------------------------------------------


def test_known_duration_ms_used_directly_not_word_count() -> None:
    """AC 6: when known_duration_ms is provided, it is used directly as the
    total duration — the word-count/words_per_minute computation must not run
    at all (proven by passing a script whose word-count estimate would give a
    very different number than known_duration_ms)."""
    from app.modules.content.pipeline.graph import _estimate_slide_timestamps

    slides = [{"slide_id": "s0"}]
    # 3-word script at wpm=150 would estimate 1200ms -- known_duration_ms below
    # is deliberately a very different number to prove it, not the estimate,
    # wins.
    ts = _estimate_slide_timestamps(
        slides,
        "Entropy measures disorder.",
        words_per_minute=150,
        default_ms_per_slide=5000,
        known_duration_ms=9999,
    )
    assert len(ts) == 1
    assert ts[0] == {"slide_id": "s0", "start_ms": 0, "end_ms": 9999}


def test_known_duration_ms_none_preserves_exact_prior_estimate_behavior() -> None:
    """AC 6/AC 10: known_duration_ms omitted (None, the default) must
    reproduce the EXACT prior word-count-estimate behavior — this is the
    regression guard for every existing caller/test that never passes the
    new keyword."""
    from app.modules.content.pipeline.graph import _estimate_slide_timestamps

    slides = [{"slide_id": "s0"}, {"slide_id": "s1"}]
    ts = _estimate_slide_timestamps(
        slides,
        "Entropy measures disorder.",  # 3 words
        words_per_minute=150,
        default_ms_per_slide=5000,
    )
    expected_total_ms = round(3 / 150 * 60_000)  # = 1200
    assert ts[-1]["end_ms"] == expected_total_ms
    assert ts[0]["start_ms"] == 0
    assert ts[0]["end_ms"] == ts[1]["start_ms"]


# ---------------------------------------------------------------------------
# package_builder_node: wiring duration_ms_by_id through to timestamps
# ---------------------------------------------------------------------------

FAKE_BOOK_ID = "32323232-3232-3232-3232-323232323232"
FAKE_CHAPTER_ID = "33333333-3333-3333-3333-333333333333"

PB_LESSON_PLAN: dict[str, Any] = {
    "title": "Intro to Thermodynamics",
    "subject": "Physics",
    "objectives": ["Understand entropy"],
    "complexity_level": "medium",
    "total_segments": 1,
    "total_duration_min": 6.0,
    "segments": [
        {
            "segment_id": "sec_0",
            "title": "Entropy Basics",
            "summary": "Intro to entropy.",
            "duration_min": 6.0,
        },
    ],
}

PB_COMPLEXITY_SCORES: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "level": "medium",
        "cognitive_load": "moderate",
        "abstraction_level": "concrete",
        "prerequisite_concepts": [],
        "narration_style": "conversational",
        "quiz_difficulty": "medium",
        "intervention_sensitivity": 0.4,
    },
]

# A single slide per segment -> timestamps has exactly one entry, so its
# end_ms IS the segment's whole computed duration -- the simplest possible
# lens onto "did package_builder use the real duration or the word-count
# estimate?"
PB_SLIDES: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "slide_id": "slide_sec_0_0",
            "title": "What is Entropy?",
            "bullets": ["Point A"],
            "image_url": None,
            "fallback_image_url": None,
        },
    },
]

PB_SLIDE_IMAGES: list[dict[str, Any]] = [
    {"slide_id": "slide_sec_0_0", "image_url": None},
]

# "Entropy measures disorder." = 3 words -> word-count estimate at the
# default wpm=150 setting is round(3/150*60_000) == 1200ms -- deliberately
# far from REAL_MP3_BYTES's real ~2612ms so the two sources are
# unmistakably distinguishable in an assertion.
PB_SCRIPT = "Entropy measures disorder."

PB_NARRATION_SCRIPTS: list[dict[str, Any]] = [
    {"segment_id": "sec_0", "script": PB_SCRIPT},
]

PB_QUIZ_QUESTIONS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "question_id": "quiz_sec_0",
            "type": "mcq",
            "question": "What is entropy?",
            "options": ["Disorder", "Order", "Mass", "Energy"],
            "correct_index": 0,
            "explanation": "Entropy measures disorder.",
            "difficulty": "medium",
        },
    },
]

PB_GLOSSARY: list[dict[str, Any]] = []

PB_INTERVENTION_PROMPTS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "distraction": ["a", "b", "c"],
            "confusion": ["a", "b", "c"],
            "fatigue": ["a", "b", "c"],
        },
    },
]


def _pb_audio_assets(duration_ms: float | None) -> list[dict[str, Any]]:
    entry: dict[str, Any] = {
        "segment_id": "sec_0",
        "data": {
            "script": PB_SCRIPT,
            "audio_url": f"{FAKE_LESSON_ID}/sec_0.mp3",
            "audio_provider": "sarvam",
            "timestamps": [],
        },
    }
    # AC 4's real shape: duration_ms is a SIBLING key to "data".
    entry["duration_ms"] = duration_ms
    return [entry]


def _pb_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "lesson_plan": PB_LESSON_PLAN,
        "complexity_scores": PB_COMPLEXITY_SCORES,
        "slides": PB_SLIDES,
        "slide_images": PB_SLIDE_IMAGES,
        "audio_assets": _pb_audio_assets(_real_mp3_duration_ms()),
        "narration_scripts": PB_NARRATION_SCRIPTS,
        "quiz_questions": PB_QUIZ_QUESTIONS,
        "glossary": PB_GLOSSARY,
        "intervention_prompts": PB_INTERVENTION_PROMPTS,
        "progress_pct": 93.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_pb_supabase(chapter_id: str = FAKE_CHAPTER_ID) -> tuple[MagicMock, MagicMock, MagicMock]:
    jobs_data = {"node_outputs": {"chunk": {"chapter_id": chapter_id, "chunks": []}}}
    jobs_table = MagicMock()
    jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        jobs_data
    )
    jobs_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    lessons_table = MagicMock()
    lessons_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    def _table_router(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs_table
        if name == "lessons":
            return lessons_table
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table_router
    sb.storage = MagicMock()
    return sb, jobs_table, lessons_table


@pytest.mark.unit
@pytest.mark.asyncio
async def test_package_builder_uses_real_duration_not_word_count_estimate() -> None:
    """AC 7/AC 8 — THE headline RED/GREEN test for this story.

    Pre-fix: package_builder_node has no `duration_ms_by_id` lookup and never
    passes `known_duration_ms` to `_estimate_slide_timestamps`, so the single
    slide's `end_ms` is ALWAYS the word-count estimate (1200ms for this
    fixture's 3-word script at wpm=150), regardless of what `duration_ms` the
    audio_assets wrapper carries. This test asserts the REAL, tinytag-measured
    value (~2612ms) instead — it fails against the unfixed code with
    `assert 1200 == 2612` (or equivalent), and passes once package_builder_node
    actually reads and uses the sibling `duration_ms` key.
    """
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_pb_supabase()
    real_duration_ms = _real_mp3_duration_ms()
    word_count_estimate_ms = round(3 / 150 * 60_000)
    assert real_duration_ms != word_count_estimate_ms, (
        "fixture must diverge from the estimate for this test to prove anything"
    )

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_pb_state())

    seg0 = result["lesson_package"]["segments"][0]
    ts = seg0["narration"]["timestamps"]
    assert len(ts) == 1
    assert ts[0]["end_ms"] == real_duration_ms
    assert ts[0]["end_ms"] != word_count_estimate_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_package_builder_falls_back_to_word_count_estimate_when_duration_unknown() -> None:
    """AC 10: when duration_ms is None (browser fallback / tinytag parse
    failure upstream), package_builder_node's timestamps must be IDENTICAL to
    the pre-existing word-count-estimate output — zero behavior change for
    lessons that still hit the fallback chain's last resort."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_pb_supabase()
    word_count_estimate_ms = round(3 / 150 * 60_000)

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_pb_state(audio_assets=_pb_audio_assets(None)))

    seg0 = result["lesson_package"]["segments"][0]
    ts = seg0["narration"]["timestamps"]
    assert ts[0]["end_ms"] == word_count_estimate_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_package_builder_missing_duration_ms_key_entirely_falls_back_too() -> None:
    """AC 10 (defensive): an audio_assets entry with NO "duration_ms" key at
    all (e.g. an ARQ-retry checkpoint written before this story shipped) must
    behave exactly like duration_ms=None -- .get() returns None, not KeyError."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_pb_supabase()
    word_count_estimate_ms = round(3 / 150 * 60_000)
    legacy_entry = [
        {
            "segment_id": "sec_0",
            "data": {
                "script": PB_SCRIPT,
                "audio_url": f"{FAKE_LESSON_ID}/sec_0.mp3",
                "audio_provider": "sarvam",
                "timestamps": [],
            },
            # no "duration_ms" key at all
        }
    ]

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_pb_state(audio_assets=legacy_entry))

    seg0 = result["lesson_package"]["segments"][0]
    ts = seg0["narration"]["timestamps"]
    assert ts[0]["end_ms"] == word_count_estimate_ms


# ---------------------------------------------------------------------------
# Round 2 review additions
# ---------------------------------------------------------------------------
#
# The four tests below close gaps raised in the real /bmad-code-review Round 2
# (see this story's "Senior Developer Review — Round 2" section):
#   - a multi-segment, mixed-duration-outcome scenario in ONE package_builder_
#     node call (Blind Hunter + Scale & Load Hunter both flagged the absence
#     of this as an untested-but-plausible independence assumption)
#   - a non-numeric/NaN duration_ms crash risk in duration_ms_by_id (Edge Case
#     Hunter) — this is a REAL, confirmed-by-execution crash fixed in this
#     round, not a hypothetical
#   - a JSONB checkpoint round-trip for the new field (Blind Hunter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_segments_with_different_duration_outcomes_do_not_leak() -> None:
    """Round 2 (Blind Hunter): no test previously ran package_builder_node
    over TWO segments where one has a real measured duration and the other
    has duration_ms=None in the SAME call — coverage relied on "plain for
    loop, no shared mutable state" reasoning rather than a direct assertion.
    Proves it directly: sec_0 gets the real ~2612ms fixture duration, sec_1
    gets None (falls back to its own, different word-count estimate) — and
    neither segment's timestamps are contaminated by the other's duration
    source."""
    from app.modules.content.pipeline.graph import package_builder_node

    lesson_plan = {
        **PB_LESSON_PLAN,
        "total_segments": 2,
        "segments": [
            *PB_LESSON_PLAN["segments"],
            {
                "segment_id": "sec_1",
                "title": "Heat Transfer",
                "summary": "Intro to heat transfer.",
                "duration_min": 4.0,
            },
        ],
    }
    complexity_scores = [
        *PB_COMPLEXITY_SCORES,
        {**PB_COMPLEXITY_SCORES[0], "segment_id": "sec_1"},
    ]
    sec1_script = "Heat always flows from hot to cold objects here."  # 9 words
    slides = [
        *PB_SLIDES,
        {
            "segment_id": "sec_1",
            "data": {
                "slide_id": "slide_sec_1_0",
                "title": "What is Heat Transfer?",
                "bullets": ["Point A"],
                "image_url": None,
                "fallback_image_url": None,
            },
        },
    ]
    slide_images = [*PB_SLIDE_IMAGES, {"slide_id": "slide_sec_1_0", "image_url": None}]
    narration_scripts = [
        *PB_NARRATION_SCRIPTS,
        {"segment_id": "sec_1", "script": sec1_script},
    ]
    quiz_questions = [
        *PB_QUIZ_QUESTIONS,
        {
            "segment_id": "sec_1",
            "data": {
                "question_id": "quiz_sec_1",
                "type": "mcq",
                "question": "Which way does heat flow?",
                "options": ["Hot to cold", "Cold to hot", "Neither", "Both"],
                "correct_index": 0,
                "explanation": "Heat flows from hot to cold.",
                "difficulty": "medium",
            },
        },
    ]
    intervention_prompts = [
        *PB_INTERVENTION_PROMPTS,
        {"segment_id": "sec_1", "data": PB_INTERVENTION_PROMPTS[0]["data"]},
    ]
    audio_assets = [
        *_pb_audio_assets(_real_mp3_duration_ms()),  # sec_0: real duration
        {
            "segment_id": "sec_1",
            "data": {
                "script": sec1_script,
                "audio_url": f"{FAKE_LESSON_ID}/sec_1.mp3",
                "audio_provider": "browser",
                "timestamps": [],
            },
            "duration_ms": None,  # sec_1: unknown -> word-count fallback
        },
    ]

    sb, _, _ = _mock_pb_supabase()
    real_duration_ms = _real_mp3_duration_ms()
    sec1_word_count_estimate_ms = round(9 / 150 * 60_000)
    assert real_duration_ms != sec1_word_count_estimate_ms

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(
            _pb_state(
                lesson_plan=lesson_plan,
                complexity_scores=complexity_scores,
                slides=slides,
                slide_images=slide_images,
                narration_scripts=narration_scripts,
                quiz_questions=quiz_questions,
                intervention_prompts=intervention_prompts,
                audio_assets=audio_assets,
            )
        )

    segs = {s["segment_id"]: s for s in result["lesson_package"]["segments"]}
    assert segs["sec_0"]["narration"]["timestamps"][0]["end_ms"] == real_duration_ms
    assert segs["sec_1"]["narration"]["timestamps"][0]["end_ms"] == sec1_word_count_estimate_ms
    # The cross-contamination this test exists to rule out: sec_1 must NOT
    # have picked up sec_0's real duration, and sec_0 must NOT have fallen
    # back to an estimate.
    assert segs["sec_1"]["narration"]["timestamps"][0]["end_ms"] != real_duration_ms
    assert segs["sec_0"]["narration"]["timestamps"][0]["end_ms"] != sec1_word_count_estimate_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_numeric_duration_ms_does_not_crash_package_builder() -> None:
    """Round 2 (Edge Case Hunter) — CONFIRMED, not hypothetical: a
    schema-drifted or hand-edited `lesson_jobs` checkpoint could carry a
    non-numeric `duration_ms` (e.g. a string). Pre-fix, `duration_ms_by_id`
    trusted it as-is and `_estimate_slide_timestamps`'s `round(known_duration_
    ms)` raised `TypeError`, crashing the WHOLE node — not just degrading the
    one malformed segment, contradicting this node's own guarantee. Proves
    the fix: the segment degrades to the word-count estimate instead."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_pb_supabase()
    word_count_estimate_ms = round(3 / 150 * 60_000)
    malformed_entry = _pb_audio_assets(None)
    malformed_entry[0]["duration_ms"] = "not-a-number"

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_pb_state(audio_assets=malformed_entry))

    seg0 = result["lesson_package"]["segments"][0]
    ts = seg0["narration"]["timestamps"]
    assert ts[0]["end_ms"] == word_count_estimate_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nan_duration_ms_does_not_crash_package_builder() -> None:
    """Round 2 (Edge Case Hunter) — the NaN sibling of the test above:
    `round(float("nan"))` raises `ValueError`, a DIFFERENT exception type
    than the non-numeric case, so both are proven separately rather than
    assuming one covers the other."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_pb_supabase()
    word_count_estimate_ms = round(3 / 150 * 60_000)
    malformed_entry = _pb_audio_assets(None)
    malformed_entry[0]["duration_ms"] = float("nan")

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_pb_state(audio_assets=malformed_entry))

    seg0 = result["lesson_package"]["segments"][0]
    ts = seg0["narration"]["timestamps"]
    assert ts[0]["end_ms"] == word_count_estimate_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_segment_id_in_audio_assets_duration_ms_keeps_last_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Round 2 (Cynical/Blind Hunter): `duration_ms_by_id`'s original dict
    comprehension bypassed `_index_by_segment_id`'s duplicate-segment_id
    warning log, unlike the sibling `audio_by_id` map built from the same
    list two lines above it -- an operator debugging a duplicate/retried
    dispatch would see a log for the data side of the incident but not the
    duration side. The rewritten loop now logs it too; this test proves it
    fires (not just that "last one wins" resolves without crashing, which
    the earlier missing-key/fallback tests already established)."""
    import logging

    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_pb_supabase()
    duplicated = [
        *_pb_audio_assets(1000.0),
        *_pb_audio_assets(_real_mp3_duration_ms()),  # same segment_id, last one wins
    ]

    with (
        caplog.at_level(logging.WARNING),
        patch("app.core.db.get_supabase", return_value=sb),
    ):
        result = await package_builder_node(_pb_state(audio_assets=duplicated))

    seg0 = result["lesson_package"]["segments"][0]
    ts = seg0["narration"]["timestamps"]
    # "Last one wins" -- the real fixture duration, not the first 1000.0.
    assert ts[0]["end_ms"] == _real_mp3_duration_ms()
    assert any(
        "duplicate segment_id" in record.message and "duration_ms" in record.message
        for record in caplog.records
    ), "the duplicate must be logged, matching audio_by_id's existing observability"


def test_estimate_slide_timestamps_rejects_non_finite_known_duration_directly() -> None:
    """Round 2 (Edge Case Hunter) — defence-in-depth unit test at the
    cheapest level: `_estimate_slide_timestamps` is a public module symbol
    other future callers could reach directly (not only through
    package_builder_node's now-validated `duration_ms_by_id`), so it repeats
    the finiteness check itself. NaN and +/-inf must all fall back to the
    word-count estimate, not propagate into `round()`."""
    from app.modules.content.pipeline.graph import _estimate_slide_timestamps

    slides = [{"slide_id": "s0"}]
    expected = _estimate_slide_timestamps(
        slides,
        "Entropy measures disorder.",
        words_per_minute=150,
        default_ms_per_slide=5000,
    )
    for bad_value in (float("nan"), float("inf"), float("-inf")):
        ts = _estimate_slide_timestamps(
            slides,
            "Entropy measures disorder.",
            words_per_minute=150,
            default_ms_per_slide=5000,
            known_duration_ms=bad_value,
        )
        assert ts == expected, f"known_duration_ms={bad_value!r} must fall back to the estimate"


def test_duration_ms_survives_a_json_checkpoint_round_trip() -> None:
    """Round 2 (Blind Hunter): `audio_assets` (carrying the new sibling
    `duration_ms` key) is written to `lesson_jobs.node_outputs` as JSONB and
    read back on an ARQ retry — every test elsewhere in this file mocks the
    Supabase client to hand back a native Python dict directly, so nothing
    exercises an actual serialize/deserialize round trip of the new key.
    `duration_ms` is only ever a plain `float | None` (no datetime, Decimal,
    or other JSON-unsafe type), so this is a narrow, cheap, direct check
    rather than a claim that this file now covers the whole checkpoint path
    end-to-end (it doesn't — see this story's Round 2 review section for the
    scope this test does and does not close)."""
    audio_assets_out = [
        {"segment_id": "sec_0", "data": {"script": "x"}, "duration_ms": 2612},
        {"segment_id": "sec_1", "data": {"script": "y"}, "duration_ms": None},
    ]
    round_tripped = json.loads(json.dumps(audio_assets_out))
    assert round_tripped == audio_assets_out
    assert round_tripped[0]["duration_ms"] == 2612
    assert round_tripped[1]["duration_ms"] is None
    # json.dumps(float("nan")) produces the non-standard `NaN` token, which
    # json.loads happily reads back as a Python float NaN -- confirming a
    # NaN value really can survive this exact checkpoint round trip and reach
    # package_builder_node as a float, which is exactly the input
    # `test_nan_duration_ms_does_not_crash_package_builder` above proves is
    # now handled, not just a value this story asserts can never occur.
    nan_round_tripped = json.loads(json.dumps({"duration_ms": float("nan")}))
    assert math.isnan(nan_round_tripped["duration_ms"])
