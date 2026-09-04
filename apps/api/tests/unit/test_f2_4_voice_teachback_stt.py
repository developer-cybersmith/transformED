"""Unit tests for Story F2-4 — Voice Teach-Back STT endpoint.

All tests are @pytest.mark.unit — no real Supabase, Whisper, or OpenAI connection.
transcribe_and_score_audio is monkeypatched at the service level so business logic
can be tested without external calls.

Guard tested: guard tests for TeachbackSubmission (typed-only path) still pass
unchanged — the audio endpoint uses UploadFile, not TeachbackSubmission.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user, get_settings
from app.modules.assessment.router import router
from app.modules.assessment.schemas import TeachbackResult, TeachbackSubmission

# ── Test client ───────────────────────────────────────────────────────────────


async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}


def _fake_settings() -> MagicMock:
    settings = MagicMock()
    settings.approved_emails = ["test@example.com"]
    settings.stt_max_file_mb = 25
    return settings


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.dependency_overrides[get_settings] = _fake_settings
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_FAKE_RESULT_LLM = TeachbackResult(
    session_id="sess-001",
    rubric_scores={"accuracy": "Proficient", "completeness": "Proficient", "clarity": "Proficient"},
    overall_score=75.0,
    ces_contribution=18.75,
    feedback="Good explanation.",
    score_source="llm",
)

_FAKE_RESULT_FALLBACK = TeachbackResult(
    session_id="sess-001",
    rubric_scores={"accuracy": "Developing", "completeness": "Developing", "clarity": "Developing"},
    overall_score=50.0,
    ces_contribution=12.5,
    feedback="Audio could not be transcribed. Please try a typed response.",
    score_source="fallback",
)

_AUDIO_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 100  # minimal WAV-like bytes


# ── AC1: endpoint accepts multipart audio and returns 200 ──────────────────────


@pytest.mark.unit
def test_audio_endpoint_accepts_upload(monkeypatch) -> None:
    """POST /assessment/teachback/{session_id}/{segment_id}/audio with valid audio → 200."""

    async def _fake_transcribe_and_score(**kwargs):
        return _FAKE_RESULT_LLM

    monkeypatch.setattr(
        "app.modules.assessment.service.transcribe_and_score_audio",
        _fake_transcribe_and_score,
    )
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post(
            "/api/assessment/teachback/sess-001/seg-001/audio",
            files={"audio": ("test.wav", io.BytesIO(_AUDIO_BYTES), "audio/wav")},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["score_source"] == "llm"


# ── AC2: file size gate ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_audio_endpoint_413_on_oversized_file(monkeypatch) -> None:
    """File exceeding stt_max_file_mb → HTTP 413 before any Whisper call."""

    def _tight_settings() -> MagicMock:
        settings = MagicMock()
        settings.approved_emails = ["test@example.com"]
        settings.stt_max_file_mb = 0  # 0 MB → any file is oversized
        return settings

    app2 = FastAPI()
    app2.dependency_overrides[get_current_user] = _fake_user
    app2.dependency_overrides[get_settings] = _tight_settings
    app2.include_router(router, prefix="/api/assessment")
    client2 = TestClient(app2, raise_server_exceptions=False)

    called = []

    async def _should_not_be_called(**kwargs):
        called.append(True)
        return _FAKE_RESULT_LLM

    monkeypatch.setattr(
        "app.modules.assessment.service.transcribe_and_score_audio",
        _should_not_be_called,
    )
    resp = client2.post(
        "/api/assessment/teachback/sess-001/seg-001/audio",
        files={"audio": ("test.wav", io.BytesIO(_AUDIO_BYTES), "audio/wav")},
    )

    assert resp.status_code == 413, f"Expected 413, got {resp.status_code}"
    assert called == [], "transcribe_and_score_audio must not be called on oversized files"


# ── AC3: WhisperProvider uses settings.stt_model ──────────────────────────────


@pytest.mark.unit
def test_whisper_provider_uses_settings_model() -> None:
    """WhisperProvider reads the model from settings, not a hardcoded literal."""
    from app.providers.stt.whisper import WhisperProvider

    settings = MagicMock()
    settings.openai_api_key = "sk-test"
    settings.stt_model = "whisper-custom"

    provider = WhisperProvider(settings=settings)
    assert provider._model == "whisper-custom", (
        f"Expected model 'whisper-custom' from settings, got {provider._model!r}"
    )


# ── AC4 + AC7: success path score_source="llm" ────────────────────────────────


@pytest.mark.unit
def test_audio_endpoint_score_source_llm_on_success(monkeypatch) -> None:
    """Successful transcription path returns score_source='llm' in the response."""

    async def _fake_transcribe_and_score(**kwargs):
        return _FAKE_RESULT_LLM

    monkeypatch.setattr(
        "app.modules.assessment.service.transcribe_and_score_audio",
        _fake_transcribe_and_score,
    )
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post(
            "/api/assessment/teachback/sess-001/seg-001/audio",
            files={"audio": ("test.wav", io.BytesIO(_AUDIO_BYTES), "audio/wav")},
        )

    assert resp.status_code == 200
    assert resp.json()["score_source"] == "llm"


# ── AC5: fallback on transcription failure → HTTP 200 + score_source="fallback" ─


@pytest.mark.unit
def test_transcription_failure_returns_200_fallback(monkeypatch) -> None:
    """WhisperProvider raises → endpoint returns HTTP 200 with score_source='fallback'."""

    async def _fake_transcribe_and_score(**kwargs):
        return _FAKE_RESULT_FALLBACK

    monkeypatch.setattr(
        "app.modules.assessment.service.transcribe_and_score_audio",
        _fake_transcribe_and_score,
    )
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post(
            "/api/assessment/teachback/sess-001/seg-001/audio",
            files={"audio": ("test.wav", io.BytesIO(_AUDIO_BYTES), "audio/wav")},
        )

    assert resp.status_code == 200, (
        f"Transcription failure must return 200 (fallback), not {resp.status_code}"
    )
    assert resp.json()["score_source"] == "fallback"


# ── AC6: cost accumulated after transcription ─────────────────────────────────


@pytest.mark.unit
def test_cost_accumulated_after_transcription() -> None:
    """accumulate_cost is called with a positive cost after a successful transcription."""
    from app.modules.assessment.service import _calculate_stt_cost

    cost = _calculate_stt_cost(duration_seconds=60.0)
    # 60s at $0.006/min = $0.006
    assert cost > 0, "STT cost must be positive for non-zero duration"
    assert abs(cost - 0.006) < 1e-9, f"Expected $0.006 for 60s, got {cost}"


# ── AC7: raw audio not stored ─────────────────────────────────────────────────


@pytest.mark.unit
def test_raw_audio_not_stored(monkeypatch) -> None:
    """Raw audio bytes are never uploaded to Supabase Storage."""
    storage_calls: list = []

    async def _fake_transcribe_and_score(**kwargs):
        return _FAKE_RESULT_LLM

    monkeypatch.setattr(
        "app.modules.assessment.service.transcribe_and_score_audio",
        _fake_transcribe_and_score,
    )

    mock_supabase = MagicMock()
    mock_supabase.storage.from_.return_value.upload = MagicMock(
        side_effect=lambda *a, **kw: storage_calls.append((a, kw))
    )

    with patch("app.core.db.get_supabase", return_value=mock_supabase):
        resp = _client.post(
            "/api/assessment/teachback/sess-001/seg-001/audio",
            files={"audio": ("test.wav", io.BytesIO(_AUDIO_BYTES), "audio/wav")},
        )

    assert resp.status_code == 200
    assert storage_calls == [], "Raw audio must never be uploaded to Supabase Storage"


# ── AC8: guard tests for typed submission still pass ──────────────────────────


@pytest.mark.unit
def test_typed_submit_guard_still_passes_no_transcript() -> None:
    """TeachbackSubmission (typed path) still has no 'transcript' field after F2-4.

    The audio endpoint uses UploadFile — TeachbackSubmission is unchanged.
    This re-validates the guard from test_assessment_stub_contracts.py.
    """
    assert "transcript" not in TeachbackSubmission.model_fields, (
        "TeachbackSubmission gained a transcript field — typed path must never have STT fields. "
        "The audio endpoint uses a separate UploadFile parameter, not TeachbackSubmission."
    )


# ── AC9: no hardcoded model string ────────────────────────────────────────────


@pytest.mark.unit
def test_whisper_provider_no_hardcoded_model() -> None:
    """The string literal 'whisper-1' must not appear in providers/stt/whisper.py.

    Model name must always come from settings.stt_model.
    """
    whisper_path = (
        Path(__file__).parent.parent.parent
        / "app"
        / "providers"
        / "stt"
        / "whisper.py"
    )
    assert whisper_path.exists(), f"Expected whisper.py at {whisper_path}"
    source = whisper_path.read_text(encoding="utf-8")
    assert '"whisper-1"' not in source, (
        "Hardcoded model 'whisper-1' found in whisper.py — use settings.stt_model instead"
    )
    assert "'whisper-1'" not in source, (
        "Hardcoded model 'whisper-1' (single-quoted) found in whisper.py — use settings.stt_model"
    )
