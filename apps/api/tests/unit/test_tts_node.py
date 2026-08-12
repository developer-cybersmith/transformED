"""
Unit tests for Story 2-8 (S2-9): tts_node real body.

Covers docs/stories/2-8-tts-node.md's ACs:
- AC-1: input is narration_scripts only.
- AC-2: Sarvam -> Azure -> Browser fallback chain, never fails the pipeline.
- AC-6: successful audio uploads to lesson-audio bucket.
- AC-7: nested {segment_id, data} output, Narration-validated.
- AC-9: cost tracked on successful synthesis.
- AC-10: idempotency checkpoint (Phase-A style).
- AC-11: empty narration_scripts does NOT raise (deliberate divergence from
  lesson_planner_node/slide_generator_node's empty-input guards).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _default_under_cost_ceiling():
    """Story 2-13/S2-13: tts_node now checks the cost ceiling per segment
    before attempting Sarvam/Azure. Default every test in this file to "not
    over ceiling" so pre-existing tests need no changes; downshift-specific
    tests override this explicitly."""
    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        yield


FAKE_LESSON_ID = "50505050-5050-5050-5050-505050505050"

NARRATION_SCRIPTS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "script": "Welcome to the lesson.",
        "narration_style": "conversational",
        "word_count": 4,
    },
    {
        "segment_id": "sec_1",
        "script": "Here is how it works.",
        "narration_style": "explanatory",
        "word_count": 5,
    },
]


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "narration_scripts": NARRATION_SCRIPTS,
        "progress_pct": 48.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_supabase(node_outputs: dict[str, Any] | None = None) -> MagicMock:
    sb = MagicMock()
    jobs_mock = MagicMock()
    jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs or {}
    }
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    sb.table.return_value = jobs_mock
    sb.storage.from_.return_value.upload.return_value = MagicMock()
    return sb


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_sarvam_success_produces_nested_narration_entries() -> None:
    """AC-2/AC-6/AC-7: Sarvam succeeds -> audio_provider='sarvam', storage
    upload called, Narration-shaped data for each segment."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state())

    assets = result["audio_assets"]
    assert len(assets) == 2
    assert assets[0]["segment_id"] == "sec_0"
    assert assets[0]["data"]["audio_provider"] == "sarvam"
    assert assets[0]["data"]["audio_url"] == f"{FAKE_LESSON_ID}/sec_0.mp3"
    assert assets[0]["data"]["script"] == "Welcome to the lesson."
    assert assets[0]["data"]["timestamps"] == []
    sb.storage.from_.assert_any_call("lesson-audio")
    upload_calls = sb.storage.from_.return_value.upload.call_args_list
    assert any(call.kwargs.get("path") == f"{FAKE_LESSON_ID}/sec_0.mp3" for call in upload_calls)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_failure_falls_back_to_azure() -> None:
    """AC-2: Sarvam raises -> Azure is tried and succeeds -> audio_provider='azure'."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.side_effect = RuntimeError("Sarvam down")
    mock_azure = AsyncMock()
    mock_azure.synthesize.return_value = (b"AZURE_AUDIO", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.providers.tts.azure.AzureTTSProvider", return_value=mock_azure),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    assets = result["audio_assets"]
    assert assets[0]["data"]["audio_provider"] == "azure"
    assert assets[0]["data"]["audio_url"] == f"{FAKE_LESSON_ID}/sec_0.mp3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_both_providers_fail_falls_back_to_browser_never_raises() -> None:
    """AC-2: both Sarvam and Azure fail -> audio_provider='browser', audio_url='',
    no exception, no storage upload, no cost accumulated."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.side_effect = RuntimeError("Sarvam down")
    mock_azure = AsyncMock()
    mock_azure.synthesize.side_effect = RuntimeError("Azure down")
    sb = _mock_supabase()
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.providers.tts.azure.AzureTTSProvider", return_value=mock_azure),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        result = await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    assets = result["audio_assets"]
    assert assets[0]["data"]["audio_provider"] == "browser"
    assert assets[0]["data"]["audio_url"] == ""
    sb.storage.from_.return_value.upload.assert_not_called()
    mock_accumulate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_over_ceiling_skips_paid_providers_and_downshifts_to_browser() -> None:
    """Story 2-13/S2-13 AC-3: when check_ceiling() returns True for a segment,
    Sarvam/Azure are never constructed/called for that segment — it degrades
    straight to the browser fallback (audio_provider='browser', cost=0.0),
    and a single downshift record is written for the whole node run."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam_cls = MagicMock()
    mock_azure_cls = MagicMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", mock_sarvam_cls),
        patch("app.providers.tts.azure.AzureTTSProvider", mock_azure_cls),
        patch(
            "app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)
        ) as mock_check_ceiling,
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state())  # 2 segments in NARRATION_SCRIPTS

    assets = result["audio_assets"]
    assert len(assets) == 2
    assert all(a["data"]["audio_provider"] == "browser" for a in assets)
    assert all(a["data"]["audio_url"] == "" for a in assets)
    mock_sarvam_cls.assert_not_called()
    mock_azure_cls.assert_not_called()

    # Story 2-13/S2-13 review fix: the downshift record must survive into the
    # node's OWN final checkpoint write, and fire once for the whole node
    # run (2 segments both over ceiling), not once per segment.
    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    written_node_outputs = checkpoint_calls[0]["node_outputs"]
    assert "tts_node" in written_node_outputs
    downshifts = written_node_outputs["_cost_downshifts"]
    assert len(downshifts) == 1
    assert downshifts[0]["node"] == "tts_node"
    assert downshifts[0]["from_model_or_provider"] == "sarvam/azure"
    assert downshifts[0]["to_model_or_provider"] == "browser"
    assert mock_check_ceiling.call_count == 2  # once per segment
    assert all(c.args == (FAKE_LESSON_ID,) for c in mock_check_ceiling.call_args_list)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_narration_scripts_does_not_raise() -> None:
    """AC-11: empty narration_scripts produces audio_assets=[], no exception —
    deliberate divergence from lesson_planner_node/slide_generator_node's
    empty-input guards (TTS never hard-fails the pipeline)."""
    from app.modules.content.pipeline.graph import tts_node

    sb = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await tts_node(_base_state(narration_scripts=[]))

    assert result["audio_assets"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_cache_hit_skips_all_synthesis() -> None:
    """AC-10: a pre-existing node_outputs['tts_node'] checkpoint is returned
    as-is with zero provider calls."""
    from app.modules.content.pipeline.graph import tts_node

    cached_assets = [
        {
            "segment_id": "sec_0",
            "data": {
                "script": "cached",
                "audio_url": "x/sec_0.mp3",
                "audio_provider": "sarvam",
                "timestamps": [],
            },
        }
    ]
    mock_sarvam = AsyncMock()
    sb = _mock_supabase(node_outputs={"tts_node": cached_assets})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
    ):
        result = await tts_node(_base_state())

    assert result["audio_assets"] == cached_assets
    mock_sarvam.synthesize.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_run_writes_checkpoint() -> None:
    """AC-10: a successful run writes last_node + node_outputs."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    checkpoint_calls = [
        call.args[0]
        for call in sb.table.return_value.update.call_args_list
        if "node_outputs" in call.args[0]
    ]
    assert len(checkpoint_calls) == 1
    assert checkpoint_calls[0]["last_node"] == "tts_node"
    assert "tts_node" in checkpoint_calls[0]["node_outputs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_accumulated_on_successful_synthesis() -> None:
    """AC-9: a successful Sarvam/Azure call accumulates cost."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    mock_accumulate.assert_called_once()
    call_args = mock_accumulate.call_args
    assert call_args.args[0] == FAKE_LESSON_ID


# ---------------------------------------------------------------------------
# 2026-07-15 code review patches
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_entry_degrades_that_segment_only_not_whole_node() -> None:
    """Review finding (Blind Hunter + Edge Case Hunter): a malformed entry
    (missing 'script') must degrade JUST that segment to browser fallback,
    not crash the whole node — other segments still process normally."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    malformed = {"segment_id": "sec_bad"}  # missing "script"
    scripts = [malformed, NARRATION_SCRIPTS[0]]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=scripts))

    assets = result["audio_assets"]
    assert len(assets) == 2, "the whole node must not crash — both entries produce output"
    assert assets[0]["segment_id"] == "sec_bad"
    assert assets[0]["data"]["audio_provider"] == "browser"
    assert assets[0]["data"]["audio_url"] == ""
    # The well-formed second entry still processes normally.
    assert assets[1]["segment_id"] == "sec_0"
    assert assets[1]["data"]["audio_provider"] == "sarvam"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsafe_segment_id_degrades_to_browser_fallback() -> None:
    """Review finding (Blind Hunter): a segment_id containing path-traversal
    characters is rejected before being used in a storage path, degrading
    that segment to browser fallback rather than uploading unsafely."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    unsafe_entry = {
        "segment_id": "../../etc/passwd",
        "script": "hi",
        "narration_style": "x",
        "word_count": 1,
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=[unsafe_entry]))

    assets = result["audio_assets"]
    assert assets[0]["data"]["audio_provider"] == "browser"
    assert assets[0]["data"]["audio_url"] == ""
    sb.storage.from_.return_value.upload.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_uses_upsert_true() -> None:
    """Review finding (Edge Case Hunter): the storage upload must pass
    upsert=true so an ARQ retry re-uploading to the same path doesn't
    conflict."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    upload_call = sb.storage.from_.return_value.upload.call_args
    assert upload_call.kwargs["file_options"]["upsert"] == "true"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_narration_scripts_writes_checkpoint() -> None:
    """Review finding (Blind Hunter): the empty-input branch must also write
    a checkpoint, matching the non-empty path's contract."""
    from app.modules.content.pipeline.graph import tts_node

    sb = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        await tts_node(_base_state(narration_scripts=[]))

    checkpoint_calls = [
        call.args[0]
        for call in sb.table.return_value.update.call_args_list
        if "node_outputs" in call.args[0]
    ]
    assert len(checkpoint_calls) == 1
    assert checkpoint_calls[0]["node_outputs"]["tts_node"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sarvam_empty_audio_bytes_falls_back_to_azure() -> None:
    """Review finding (Edge Case Hunter): Sarvam returning empty (falsy)
    audio bytes without raising must still fall through to Azure, not be
    accepted as a success."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"", [])  # falsy but not None
    mock_azure = AsyncMock()
    mock_azure.synthesize.return_value = (b"AZURE_AUDIO", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.providers.tts.azure.AzureTTSProvider", return_value=mock_azure),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    assert result["audio_assets"][0]["data"]["audio_provider"] == "azure"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_azure_empty_audio_bytes_falls_back_to_browser() -> None:
    """2026-07-20 review finding (Test Coverage layer): the symmetric hop to
    the Sarvam-empty case was untested — Azure returning empty (falsy) audio
    bytes without raising must fall through to the browser fallback, not be
    accepted as a 0-byte 'success' uploaded to Storage."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.side_effect = RuntimeError("Sarvam down")
    mock_azure = AsyncMock()
    mock_azure.synthesize.return_value = (b"", [])  # falsy but not None
    sb = _mock_supabase()
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.providers.tts.azure.AzureTTSProvider", return_value=mock_azure),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        result = await tts_node(_base_state(narration_scripts=[NARRATION_SCRIPTS[0]]))

    asset = result["audio_assets"][0]["data"]
    assert asset["audio_provider"] == "browser"
    assert asset["audio_url"] == ""  # no 0-byte upload
    sb.storage.from_.return_value.upload.assert_not_called()
    mock_accumulate.assert_not_called()


# ---------------------------------------------------------------------------
# Story 3-37: Node 8 narration hard cap (decisionupdate.md §8)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments() -> None:
    """Story 3-37 AC 3/4/5/6: 4 segments of 4,000 chars each (16,000 total)
    exceed the 10,000-char lesson-wide cap. The 3rd segment (crosses the
    boundary at 8,000 + 4,000 > 10,000) must be truncated to exactly the
    remaining 2,000-char budget and STILL synthesized; the 4th segment must
    be treated as empty — zero chars ever reach a TTS provider for it, and
    it degrades through the existing browser-fallback shape. The sum of
    characters actually sent to any provider must never exceed the cap, and
    an explicit, always-present degradation record must be persisted.

    RED (pre-fix): nothing today caps the lesson-wide total — all 16,000
    chars reach `_synthesize_with_fallback` unmodified, and
    `node_outputs["narration_cap_applied"]` does not exist at all (KeyError
    on the assertion below).
    """
    from app.modules.content.pipeline.graph import tts_node

    scripts = [
        {"segment_id": "sec_0", "script": "A" * 4000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_1", "script": "B" * 4000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_2", "script": "C" * 4000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_3", "script": "D" * 4000, "narration_style": "x", "word_count": 1},
    ]

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=scripts))

    # AC 5: total characters actually sent to the TTS provider never exceeds
    # the cap — sum every text argument Sarvam was actually invoked with.
    chars_sent = sum(len(call.args[0]) for call in mock_sarvam.synthesize.call_args_list)
    assert chars_sent <= 10000, (
        f"{chars_sent} chars reached the TTS provider — the lesson-wide cap was not enforced"
    )

    # AC 3: the crossing segment (sec_2) was truncated to the exact remainder.
    assets = result["audio_assets"]
    by_id = {a["segment_id"]: a["data"] for a in assets}
    assert by_id["sec_0"]["script"] == "A" * 4000
    assert by_id["sec_1"]["script"] == "B" * 4000
    assert by_id["sec_2"]["script"] == "C" * 2000

    # AC 4: the subsequent segment (sec_3) was zeroed and degraded through
    # the existing browser-fallback shape — no provider call for it at all.
    assert by_id["sec_3"]["script"] == ""
    assert by_id["sec_3"]["audio_provider"] == "browser"
    assert by_id["sec_3"]["audio_url"] == ""
    sec_3_calls = [c for c in mock_sarvam.synthesize.call_args_list if c.args[0] == "D" * 4000]
    assert sec_3_calls == [], "sec_3's full script must never reach a TTS provider"

    # AC 6: explicit, always-present degradation record on the SAME write.
    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": True,
        "original_total_chars": 16000,
        "capped_total_chars": 10000,
        "affected_segment_ids": ["sec_2", "sec_3"],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lesson_wide_narration_under_cap_is_completely_unaffected() -> None:
    """Story 3-37 AC 2/9: a lesson whose combined narration is well under the
    10,000-char cap must be completely unaffected — every script byte-for-
    byte unchanged, no segment skipped, and the degradation record reports
    capped=False with the two totals equal and an empty affected list."""
    from app.modules.content.pipeline.graph import tts_node

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state())  # 2 short segments, well under 10,000 chars

    assets = result["audio_assets"]
    by_id = {a["segment_id"]: a["data"] for a in assets}
    assert by_id["sec_0"]["script"] == "Welcome to the lesson."
    assert by_id["sec_1"]["script"] == "Here is how it works."
    total_chars = len("Welcome to the lesson.") + len("Here is how it works.")

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": False,
        "original_total_chars": total_chars,
        "capped_total_chars": total_chars,
        "affected_segment_ids": [],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_exact_boundary_fit_is_not_truncated() -> None:
    """Story 3-37 round-1 self-review edge case: a segment whose length
    exactly exhausts the remaining budget (running_total + len(script) ==
    max_chars) must NOT be treated as truncated — only a segment that
    exceeds the remaining budget counts as affected. Only the segment
    AFTER the exact-fit one should be zeroed."""
    from app.modules.content.pipeline.graph import tts_node

    scripts = [
        {"segment_id": "sec_0", "script": "A" * 10000, "narration_style": "x", "word_count": 1},
        {"segment_id": "sec_1", "script": "B" * 100, "narration_style": "x", "word_count": 1},
    ]

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=scripts))

    by_id = {a["segment_id"]: a["data"] for a in result["audio_assets"]}
    assert by_id["sec_0"]["script"] == "A" * 10000  # exact fit, unmodified
    assert by_id["sec_1"]["script"] == ""  # zeroed, budget already exhausted

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": True,
        "original_total_chars": 10100,
        "capped_total_chars": 10000,
        "affected_segment_ids": ["sec_1"],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_empty_narration_scripts_list_is_uncapped_by_construction() -> None:
    """Story 3-37 AC 6, Round-2 review (Cynical Review): a dedicated test for
    the genuinely-empty-list case, distinct from
    test_lesson_wide_narration_under_cap_is_completely_unaffected (which
    only ever exercises 2 non-empty short segments). An empty
    narration_scripts must still get an explicit, always-present
    capped=False record — never skip the write just because there was
    nothing to cap."""
    from app.modules.content.pipeline.graph import tts_node

    sb = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await tts_node(_base_state(narration_scripts=[]))

    assert result["audio_assets"] == []

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record == {
        "capped": False,
        "original_total_chars": 0,
        "capped_total_chars": 0,
        "affected_segment_ids": [],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_reorders_out_of_order_fan_in_by_true_section_index() -> None:
    """Story 3-37 Round-2 review (Cynical Review + Edge Case Hunter,
    independently): narration_scripts is Annotated[list, operator.add], fed
    by Send()-dispatched calls into the same LangGraph superstep with NO
    cross-call ordering guarantee (narration_generator_node's own
    docstring: "Send()-dispatched calls do not all resolve in lockstep").
    Hand-construct the fan-in list arriving OUT of section order — the
    LAST section by real segment_id index (section_3) must still be the
    one that gets zeroed, never whichever entry happened to land last in
    the (scrambled) list."""
    from app.modules.content.pipeline.graph import tts_node

    # Arrival order: 2, 0, 3, 1 — deliberately not lesson order.
    scripts = [
        {"segment_id": "section_2_c", "script": "C" * 4000, "narration_style": "x"},
        {"segment_id": "section_0_a", "script": "A" * 4000, "narration_style": "x"},
        {"segment_id": "section_3_d", "script": "D" * 4000, "narration_style": "x"},
        {"segment_id": "section_1_b", "script": "B" * 4000, "narration_style": "x"},
    ]

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=scripts))

    by_id = {a["segment_id"]: a["data"] for a in result["audio_assets"]}
    # True lesson order is 0,1,2,3 — sections 0 and 1 fit fully (8,000
    # chars), section 2 crosses the boundary and is truncated to the
    # remaining 2,000, section 3 (the REAL last section) is zeroed — even
    # though it arrived BEFORE section_1 in the raw fan-in list.
    assert by_id["section_0_a"]["script"] == "A" * 4000
    assert by_id["section_1_b"]["script"] == "B" * 4000
    assert by_id["section_2_c"]["script"] == "C" * 2000
    assert by_id["section_3_d"]["script"] == ""

    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    cap_record = checkpoint_calls[0]["node_outputs"]["narration_cap_applied"]
    assert cap_record["affected_segment_ids"] == ["section_2_c", "section_3_d"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_skips_non_dict_entry_without_crashing_node() -> None:
    """Story 3-37 Round-2 review (Cynical Review): a non-dict entry in
    narration_scripts (bare string, from a schema-drifted or hand-edited
    checkpoint — the exact case package_builder_node._index_by_segment_id
    already defends against a few hundred lines below in this file) must
    be logged and dropped, never crash the whole node on `entry.get(...)`
    — matches this node's own "never hard-fails" guarantee."""
    from app.modules.content.pipeline.graph import tts_node

    scripts: list[Any] = [
        {"segment_id": "sec_0", "script": "hello", "narration_style": "x"},
        "not-a-dict-entry",
        {"segment_id": "sec_1", "script": "world", "narration_style": "x"},
    ]

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=scripts))

    by_id = {a["segment_id"]: a["data"] for a in result["audio_assets"]}
    assert set(by_id) == {"sec_0", "sec_1"}
    assert by_id["sec_0"]["script"] == "hello"
    assert by_id["sec_1"]["script"] == "world"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_cap_truncation_does_not_split_devanagari_combining_mark() -> None:
    """Story 3-37 Round-2 review (Cynical Review + Edge Case Hunter,
    independently): Sarvam Bulbul v2 (this repo's primary TTS provider)
    targets Indic scripts, where a raw character-index slice can land
    between a base consonant and a dependent vowel sign (matra) that is a
    SEPARATE Unicode codepoint — producing a technically-valid but
    linguistically-broken orphaned base character right at the cap
    boundary. The truncation must back off to the nearest safe boundary
    instead."""
    from app.modules.content.pipeline.graph import tts_node

    # "क" (KA, base) + "ि" (VOWEL SIGN I, combining) sit at indices 9999 and
    # 10000 of a 10,001-char first segment — a raw script[:10000] slice
    # would keep KA (index 9999) but drop its vowel sign (index 10000),
    # landing precisely mid-cluster. The cap (10,000) forces this segment
    # to cross the boundary since 10,001 > 10,000.
    devanagari_pair = "कि"  # क + ि
    first_segment = ("A" * 9999) + devanagari_pair  # 10,001 chars total
    scripts = [
        {"segment_id": "sec_0", "script": first_segment, "narration_style": "x"},
        {"segment_id": "sec_1", "script": "B" * 100, "narration_style": "x"},
    ]

    mock_sarvam = AsyncMock()
    mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.tts.sarvam.SarvamTTSProvider", return_value=mock_sarvam),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await tts_node(_base_state(narration_scripts=scripts))

    by_id = {a["segment_id"]: a["data"] for a in result["audio_assets"]}
    truncated = by_id["sec_0"]["script"]
    # A naive script[:10000] slice would produce "A"*9999 + "क" — a bare
    # base character orphaned from its vowel sign. The grapheme-safe trim
    # must back off past BOTH, keeping only the plain "A" run.
    assert truncated == "A" * 9999
    assert not truncated.endswith("क")  # bare KA with no following matra
    assert "ि" not in truncated
    assert len(truncated) <= 10000
