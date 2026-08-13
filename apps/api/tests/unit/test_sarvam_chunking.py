"""
Unit tests for D74 (Story 3-42): Sarvam text chunking, request batching, and
real WAV concatenation.

Two server-validated Sarvam limits, confirmed live (not assumed from docs):
- 500 chars max per `inputs[]` string
- 3 items max per `inputs[]` array

`_chunk_narration_text` / `_batched` / `_concatenate_wav_clips` are pure
functions — tested directly, no HTTP mocking needed. The full
`_synthesize_inner` multi-batch HTTP flow is covered in
test_tts_providers.py.
"""

from __future__ import annotations

import io
import wave

import pytest

from app.providers.tts.sarvam import (
    _SARVAM_MAX_CHARS_PER_INPUT,
    _SARVAM_MAX_INPUTS_PER_REQUEST,
    _batched,
    _chunk_narration_text,
    _concatenate_wav_clips,
)


def _wav_bytes(num_frames: int, framerate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _chunk_narration_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chunk_empty_text_returns_empty_list() -> None:
    assert _chunk_narration_text("") == []


@pytest.mark.unit
def test_chunk_short_text_returns_single_unmodified_chunk() -> None:
    text = "This is short."
    assert _chunk_narration_text(text) == [text]


@pytest.mark.unit
def test_chunk_respects_max_chars_boundary() -> None:
    """The real defect: Sarvam 400s on any single input over 500 chars.
    Every chunk this function produces must be within the limit."""
    text = ("This is a real sentence about machine learning models. " * 20).strip()
    assert len(text) > _SARVAM_MAX_CHARS_PER_INPUT
    chunks = _chunk_narration_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= _SARVAM_MAX_CHARS_PER_INPUT


@pytest.mark.unit
def test_chunk_prefers_sentence_boundaries() -> None:
    """Each chunk should end at a real sentence boundary where possible, so
    narration is spoken as complete sentences, not cut mid-word."""
    text = "First sentence here. Second sentence here. Third sentence here."
    chunks = _chunk_narration_text(text, max_chars=40)
    for chunk in chunks:
        assert chunk.rstrip().endswith((".", "!", "?")) or chunk == chunks[-1]


@pytest.mark.unit
def test_chunk_never_drops_or_duplicates_words() -> None:
    """Cost accounting (COST_PER_CHAR) bills the ORIGINAL text length —
    chunking must not lose or duplicate any word."""
    text = ("Alpha bravo charlie delta echo foxtrot golf hotel india juliet. " * 10).strip()
    chunks = _chunk_narration_text(text, max_chars=80)
    original_words = text.split()
    rejoined_words = " ".join(chunks).split()
    assert rejoined_words == original_words


@pytest.mark.unit
def test_chunk_oversized_single_sentence_falls_back_to_word_boundaries() -> None:
    """LLM-generated narration is not guaranteed to respect sentence-length
    conventions — a single run-on sentence over 500 chars with no punctuation
    must still split without exceeding max_chars."""
    text = "word " * 200  # 1000 chars, zero sentence-ending punctuation
    chunks = _chunk_narration_text(text, max_chars=_SARVAM_MAX_CHARS_PER_INPUT)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= _SARVAM_MAX_CHARS_PER_INPUT


@pytest.mark.unit
def test_chunk_realistic_segment_length_matches_observed_lesson_data() -> None:
    """Regression pin against the real numbers that surfaced this defect:
    a real generated lesson's segments ran 1,351-4,069 chars, every one over
    the 500-char limit. This must never regress to accepting them whole."""
    text = ("Machine learning models require careful evaluation. " * 60).strip()
    assert 1351 <= len(text) <= 4069 or len(text) > _SARVAM_MAX_CHARS_PER_INPUT
    chunks = _chunk_narration_text(text)
    assert all(len(c) <= _SARVAM_MAX_CHARS_PER_INPUT for c in chunks)


# ---------------------------------------------------------------------------
# _batched
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batched_respects_max_inputs_per_request() -> None:
    """The real defect: Sarvam 400s on more than 3 items in one request."""
    items = [f"chunk-{i}" for i in range(8)]
    batches = _batched(items, _SARVAM_MAX_INPUTS_PER_REQUEST)
    for batch in batches:
        assert len(batch) <= _SARVAM_MAX_INPUTS_PER_REQUEST


@pytest.mark.unit
def test_batched_preserves_order_and_all_items() -> None:
    items = [f"chunk-{i}" for i in range(8)]
    batches = _batched(items, 3)
    flattened = [item for batch in batches for item in batch]
    assert flattened == items


@pytest.mark.unit
def test_batched_empty_list_returns_empty() -> None:
    assert _batched([], 3) == []


@pytest.mark.unit
def test_batched_exact_multiple_produces_full_batches_only() -> None:
    items = [f"chunk-{i}" for i in range(6)]
    batches = _batched(items, 3)
    assert batches == [items[0:3], items[3:6]]


# ---------------------------------------------------------------------------
# _concatenate_wav_clips
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_concatenate_single_clip_returns_equivalent_audio() -> None:
    clip = _wav_bytes(100)
    result = _concatenate_wav_clips([clip])
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getnframes() == 100


@pytest.mark.unit
def test_concatenate_multiple_clips_produces_one_valid_file_with_combined_length() -> None:
    """The real defect this guards: naive byte concatenation of complete WAV
    files produces an INVALID multi-header file. This proves the result is a
    single valid file the `wave` module can read start-to-finish, with the
    combined frame count of all inputs — not just the first clip's length."""
    clips = [_wav_bytes(100), _wav_bytes(150), _wav_bytes(75)]
    result = _concatenate_wav_clips(clips)
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getnframes() == 100 + 150 + 75


@pytest.mark.unit
def test_concatenate_preserves_audio_format_params() -> None:
    clips = [_wav_bytes(100, framerate=22050), _wav_bytes(100, framerate=22050)]
    result = _concatenate_wav_clips(clips)
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 22050
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2


@pytest.mark.unit
def test_concatenate_naive_byte_join_would_have_wrong_frame_count() -> None:
    """Contrast test: proves naive concatenation (what a less careful fix
    might have done) is WRONG, so the real fix's correctness is visible by
    comparison, not just asserted in isolation."""
    clips = [_wav_bytes(100), _wav_bytes(150)]
    naive = b"".join(clips)
    with wave.open(io.BytesIO(naive), "rb") as wf:
        naive_frames = wf.getnframes()
    # The naive join is readable (first clip's own valid header) but reports
    # only the FIRST clip's frame count — proving it silently drops the rest.
    assert naive_frames == 100

    correct = _concatenate_wav_clips(clips)
    with wave.open(io.BytesIO(correct), "rb") as wf:
        assert wf.getnframes() == 250
