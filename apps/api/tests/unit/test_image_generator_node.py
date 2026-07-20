"""
Unit tests for Story 2-9 (S2-10): image_generator_node real body.

Covers docs/stories/2-9-image-generator-node.md's ACs:
- AC-1: input is state["slides"] only.
- AC-2: GPT Image 1 Mini -> Imagen 4 Fast -> text-only fallback, never fails.
- AC-3: proactive cost-ceiling pre-check.
- AC-7: successful images uploaded to lesson-images bucket, upsert=true.
- AC-8: flat {slide_id, image_url} output shape.
- AC-11: per-slide failure isolation (baked in from the start).
- AC-12: slide_id path-safety validation.
- AC-13: idempotency checkpoint (Phase-A style), including empty-input case.
- AC-14: empty state["slides"] does NOT raise.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FAKE_LESSON_ID = "60606060-6060-6060-6060-606060606060"

SLIDES: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "slide_id": "slide_sec_0_0", "title": "Welcome", "bullets": ["Point A"],
            "image_url": None, "fallback_image_url": None,
        },
    },
    {
        "segment_id": "sec_1",
        "data": {
            "slide_id": "slide_sec_1_0", "title": "Mechanics", "bullets": ["Step 1"],
            "image_url": None, "fallback_image_url": None,
        },
    },
]

_FAKE_DATA_URI = f"data:image/png;base64,{base64.b64encode(b'FAKEIMG').decode()}"


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "slides": SLIDES,
        "progress_pct": 86.0,
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
async def test_happy_path_openai_success_produces_flat_slide_images() -> None:
    """AC-2/AC-7/AC-8: GPT Image succeeds -> storage upload with upsert=true,
    flat {slide_id, image_url} entries."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state())

    images = result["slide_images"]
    assert len(images) == 2
    assert images[0] == {"slide_id": "slide_sec_0_0", "image_url": f"{FAKE_LESSON_ID}/slide_sec_0_0.png"}
    upload_call = sb.storage.from_.return_value.upload.call_args_list[0]
    assert upload_call.kwargs["file_options"]["upsert"] == "true"
    assert upload_call.kwargs["file_options"]["content-type"] == "image/png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_failure_falls_back_to_imagen() -> None:
    """AC-2: GPT Image raises -> Imagen is tried and succeeds."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.side_effect = RuntimeError("GPT Image down")
    mock_imagen_provider = AsyncMock()
    mock_imagen_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.providers.image.imagen.ImagenProvider", return_value=mock_imagen_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert result["slide_images"][0]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_0_0.png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_both_providers_fail_falls_back_to_text_only_never_raises() -> None:
    """AC-2/AC-11: both providers fail -> image_url=None, no exception, no
    upload, no cost accumulated."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.side_effect = RuntimeError("GPT Image down")
    mock_imagen_provider = AsyncMock()
    mock_imagen_provider.generate.side_effect = RuntimeError("Imagen down")
    sb = _mock_supabase()
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.providers.image.imagen.ImagenProvider", return_value=mock_imagen_provider),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert result["slide_images"][0] == {"slide_id": "slide_sec_0_0", "image_url": None}
    sb.storage.from_.return_value.upload.assert_not_called()
    mock_accumulate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_ceiling_over_skips_providers_entirely() -> None:
    """AC-3: cost ceiling already over -> image_url=None, zero provider calls."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert result["slide_images"][0]["image_url"] is None
    mock_openai_provider.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_slide_entry_degrades_that_slide_only() -> None:
    """AC-11: a malformed slide entry (missing 'data'/'title'/'bullets')
    degrades JUST that slide, other slides still process normally."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    malformed = {"segment_id": "sec_bad", "data": {"slide_id": "slide_bad"}}  # missing title/bullets
    slides_in = [malformed, SLIDES[0]]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state(slides=slides_in))

    images = result["slide_images"]
    assert len(images) == 2, "the whole node must not crash"
    assert images[0] == {"slide_id": "slide_bad", "image_url": None}
    assert images[1]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_0_0.png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsafe_slide_id_degrades_to_text_only() -> None:
    """AC-12: a slide_id containing path-traversal characters is rejected
    before being used in a storage path."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    unsafe_slide = {
        "segment_id": "sec_0",
        "data": {"slide_id": "../../etc/passwd", "title": "x", "bullets": ["y"], "image_url": None, "fallback_image_url": None},
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state(slides=[unsafe_slide]))

    assert result["slide_images"][0]["image_url"] is None
    sb.storage.from_.return_value.upload.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_slides_writes_checkpoint_and_does_not_raise() -> None:
    """AC-13/AC-14: empty state["slides"] -> slide_images=[], checkpoint
    written, no exception."""
    from app.modules.content.pipeline.graph import image_generator_node

    sb = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await image_generator_node(_base_state(slides=[]))

    assert result["slide_images"] == []
    checkpoint_calls = [
        call.args[0]
        for call in sb.table.return_value.update.call_args_list
        if "node_outputs" in call.args[0]
    ]
    assert len(checkpoint_calls) == 1
    assert checkpoint_calls[0]["node_outputs"]["image_generator"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_cache_hit_skips_all_generation() -> None:
    """AC-13: a pre-existing node_outputs['image_generator'] checkpoint is
    returned as-is with zero provider calls."""
    from app.modules.content.pipeline.graph import image_generator_node

    cached_images = [{"slide_id": "slide_sec_0_0", "image_url": "x/slide_sec_0_0.png"}]
    mock_openai_provider = AsyncMock()
    sb = _mock_supabase(node_outputs={"image_generator": cached_images})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
    ):
        result = await image_generator_node(_base_state())

    assert result["slide_images"] == cached_images
    mock_openai_provider.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_run_writes_checkpoint() -> None:
    """AC-13: a successful run writes last_node + node_outputs."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(_base_state(slides=[SLIDES[0]]))

    checkpoint_calls = [
        call.args[0]
        for call in sb.table.return_value.update.call_args_list
        if "node_outputs" in call.args[0]
    ]
    assert len(checkpoint_calls) == 1
    assert checkpoint_calls[0]["last_node"] == "image_generator"
    assert "image_generator" in checkpoint_calls[0]["node_outputs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prompt_never_includes_raw_lesson_plan_or_narration() -> None:
    """AC-1: even when lesson_plan/segment_summaries/narration_scripts are
    present in state alongside slides, image prompts never reference them."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    state = _base_state(
        slides=[SLIDES[0]],
        lesson_plan={"title": "RAW LESSON PLAN MUST NEVER APPEAR"},
        segment_summaries=[{"segment_id": "sec_0", "summary": "RAW SUMMARY MUST NEVER APPEAR"}],
        narration_scripts=[{"segment_id": "sec_0", "script": "RAW NARRATION MUST NEVER APPEAR"}],
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(state)

    sent_prompt = mock_openai_provider.generate.call_args.args[0]
    assert "RAW LESSON PLAN" not in sent_prompt
    assert "RAW SUMMARY" not in sent_prompt
    assert "RAW NARRATION" not in sent_prompt
    assert "Welcome" in sent_prompt


# ---------------------------------------------------------------------------
# 2026-07-15 code review patches
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_is_accumulated_only_after_successful_upload_not_by_provider() -> None:
    """Review finding (Blind Hunter + Edge Case Hunter + Acceptance Auditor):
    cost must be accumulated by the NODE after a successful upload, not by
    the provider before the upload — verified by checking accumulate_cost
    is never called when the upload itself fails."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()
    sb.storage.from_.return_value.upload.side_effect = RuntimeError("Storage down")
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    # Upload failed -> slide degrades to text-only -> no cost for an image
    # that was generated but never persisted.
    assert result["slide_images"][0]["image_url"] is None
    mock_accumulate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_data_uri_from_provider_degrades_slide_not_uploaded_as_success() -> None:
    """Review finding (Blind Hunter + Edge Case Hunter): a malformed data URI
    (no comma / not base64-prefixed) must raise inside _decode_data_uri and
    degrade that slide, not silently upload a 0-byte 'success'."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = "not-a-real-data-uri"
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert result["slide_images"][0]["image_url"] is None
    sb.storage.from_.return_value.upload.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_dict_data_field_degrades_that_slide_only() -> None:
    """Review finding (Edge Case Hunter): entry['data'] being a non-dict
    truthy value (e.g. a string) must not raise AttributeError outside the
    per-slide try/except — it must degrade just that slide."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    mock_openai_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    bad_entry = {"segment_id": "sec_bad", "data": "oops-not-a-dict"}
    slides_in = [bad_entry, SLIDES[0]]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state(slides=slides_in))

    images = result["slide_images"]
    assert len(images) == 2, "the whole node must not crash"
    assert images[0]["image_url"] is None
    assert images[1]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_0_0.png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multiple_malformed_entries_get_unique_placeholder_slide_ids() -> None:
    """Review finding (Edge Case Hunter): two malformed entries must not both
    collapse to the same '<unknown>' slide_id."""
    from app.modules.content.pipeline.graph import image_generator_node

    sb = _mock_supabase()
    bad_entries = [{"segment_id": "a"}, {"segment_id": "b"}]

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await image_generator_node(_base_state(slides=bad_entries))

    slide_ids = [img["slide_id"] for img in result["slide_images"]]
    assert len(set(slide_ids)) == 2, f"expected unique placeholder slide_ids, got {slide_ids}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsafe_lesson_id_raises() -> None:
    """Review finding (Blind Hunter): lesson_id must be validated the same
    way slide_id is, before being used in a storage path."""
    from app.modules.content.pipeline.graph import image_generator_node

    sb = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        with pytest.raises(RuntimeError, match="unsafe lesson_id"):
            await image_generator_node(_base_state(lesson_id="../../etc/passwd", slides=[SLIDES[0]]))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_bullets_list_degrades_slide_without_calling_provider() -> None:
    """Review finding (Edge Case Hunter): an empty-but-present bullets list
    must be rejected like a malformed entry, not paid for."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_openai_provider = AsyncMock()
    sb = _mock_supabase()

    empty_bullets_slide = {
        "segment_id": "sec_0",
        "data": {"slide_id": "slide_sec_0_0", "title": "Welcome", "bullets": [], "image_url": None, "fallback_image_url": None},
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_openai_provider),
    ):
        result = await image_generator_node(_base_state(slides=[empty_bullets_slide]))

    assert result["slide_images"][0]["image_url"] is None
    mock_openai_provider.generate.assert_not_called()
