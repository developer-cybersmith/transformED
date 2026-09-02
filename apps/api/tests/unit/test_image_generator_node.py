"""
Unit tests for Story 2-9 (S2-10): image_generator_node real body.

Covers docs/stories/2-9-image-generator-node.md's ACs:
- AC-1: input is state["slides"] only.
- AC-2: Gemini "Nano Banana" -> GPT Image 2 -> text-only fallback, never fails
  (order per Story 5-8b — reversed from the original GPT-Image-primary chain
  once Imagen 4 Fast died, D121).
- AC-3: proactive cost-ceiling pre-check.
- AC-7: successful images uploaded to lesson-images bucket, upsert=true.
- AC-8: flat {slide_id, image_url} output shape.
- AC-11: per-slide failure isolation (baked in from the start).
- AC-12: slide_id path-safety validation.
- AC-13: idempotency checkpoint (Phase-A style), including empty-input case.
- AC-14: empty state["slides"] does NOT raise.

D132 (bounded concurrent generation, see D132-FIX-TRACKER.md):
- Slides actually generate concurrently, not one at a time.
- Output order (`slide_images_out`) stays index-matched to input `slides`
  even when a later slide's generation finishes before an earlier one's.
- Per-slide isolation still holds under concurrency: one slide's failure
  does not cancel or otherwise affect a concurrently-running sibling.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FAKE_LESSON_ID = "60606060-6060-6060-6060-606060606060"

SLIDES: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "slide_id": "slide_sec_0_0",
            "title": "Welcome",
            "bullets": ["Point A"],
            "image_url": None,
            "fallback_image_url": None,
        },
    },
    {
        "segment_id": "sec_1",
        "data": {
            "slide_id": "slide_sec_1_0",
            "title": "Mechanics",
            "bullets": ["Step 1"],
            "image_url": None,
            "fallback_image_url": None,
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
async def test_happy_path_gemini_success_produces_flat_slide_images() -> None:
    """AC-2/AC-7/AC-8: Gemini "Nano Banana" (primary, Story 5-8b) succeeds ->
    storage upload with upsert=true, flat {slide_id, image_url} entries."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state())

    images = result["slide_images"]
    assert len(images) == 2
    assert images[0] == {
        "slide_id": "slide_sec_0_0",
        "image_url": f"{FAKE_LESSON_ID}/slide_sec_0_0.png",
    }
    upload_call = sb.storage.from_.return_value.upload.call_args_list[0]
    assert upload_call.kwargs["file_options"]["upsert"] == "true"
    assert upload_call.kwargs["file_options"]["content-type"] == "image/png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gemini_is_tried_before_gpt_image() -> None:
    """Story 5-8b AC5: pins the fallback ORDER explicitly. Both providers are
    mocked to succeed with DIFFERENT payloads — if Gemini is genuinely tried
    first (as required), its payload is the one that reaches the slide; if a
    future change silently reverted the order (or tried both/either), GPT
    Image's payload would win instead and this test would catch it. Closes a
    real, confirmed gap: no earlier test in this suite asserted WHICH
    provider is queried first, only which one wins when the other fails."""
    from app.modules.content.pipeline.graph import image_generator_node

    gemini_data_uri = f"data:image/png;base64,{base64.b64encode(b'GEMINIIMG').decode()}"
    gpt_data_uri = f"data:image/png;base64,{base64.b64encode(b'GPTIMAGEIMG').decode()}"

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = gemini_data_uri
    mock_gpt_fallback = AsyncMock()
    mock_gpt_fallback.generate.return_value = gpt_data_uri
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch(
            "app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_gpt_fallback
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(_base_state(slides=[SLIDES[0]]))

    mock_gemini_provider.generate.assert_awaited_once()
    mock_gpt_fallback.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_d118_requests_a_widescreen_size_not_the_old_default_square() -> None:
    """D118: the player renders slide images with object-contain in a wide
    panel, sized from the image's own intrinsic ratio — a 1024x1024 square
    request produced a small square block marooned in a wide panel, visually
    indistinguishable from a fixed crop even though no CSS ever cropped it.
    Every provider call must now ask for a landscape size."""
    from app.modules.content.pipeline.graph import _SLIDE_IMAGE_SIZE, image_generator_node

    assert _SLIDE_IMAGE_SIZE != "1024x1024", "must not silently regress to the old square default"

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert mock_gemini_provider.generate.call_args.kwargs.get("size") == _SLIDE_IMAGE_SIZE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_d118_gpt_image_fallback_also_requests_the_widescreen_size() -> None:
    """The fallback provider must receive the SAME size the primary was asked
    for, not silently revert to square when Gemini fails. (Story 5-8b:
    Gemini "Nano Banana" is now primary, GPT Image 2 is now fallback.)"""
    from app.modules.content.pipeline.graph import _SLIDE_IMAGE_SIZE, image_generator_node

    mock_gemini_primary = AsyncMock()
    mock_gemini_primary.generate.side_effect = RuntimeError("Gemini down")
    mock_gpt_fallback = AsyncMock()
    mock_gpt_fallback.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_primary,
        ),
        patch(
            "app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_gpt_fallback
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert mock_gpt_fallback.generate.call_args.kwargs.get("size") == _SLIDE_IMAGE_SIZE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_d118_cost_accumulated_matches_the_size_actually_requested() -> None:
    """The cost lookup must key on the size actually used
    (_SLIDE_IMAGE_SIZE), not a stale hardcoded "1024x1024" — the real
    landscape size is priced higher than square; a stale literal would
    under-report real spend against the $3.00/lesson cost ceiling. Asserted
    dynamically against COST_PER_IMAGE[_SLIDE_IMAGE_SIZE], not a literal
    dollar figure, so this test can't silently drift from reality the way
    D120 found the constant itself had (see graph.py's own D120 comment)."""
    from app.modules.content.pipeline.graph import _SLIDE_IMAGE_SIZE, image_generator_node
    from app.providers.image.nano_banana import COST_PER_IMAGE

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        await image_generator_node(_base_state(slides=[SLIDES[0]]))

    mock_accumulate.assert_called_once_with(FAKE_LESSON_ID, COST_PER_IMAGE[_SLIDE_IMAGE_SIZE])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_d118_uploaded_bytes_are_actually_cropped_to_exact_16_9() -> None:
    """Proves _crop_to_16_9 is really wired into the node's upload path, not
    just correct in isolation — uses a REAL square PNG (unlike the other
    tests' opaque _FAKE_DATA_URI, which isn't valid image data and would
    make the crop step silently no-op via its degrade-on-error path)."""
    import base64 as b64
    from io import BytesIO

    from PIL import Image

    from app.modules.content.pipeline.graph import image_generator_node

    square = BytesIO()
    Image.new("RGB", (1024, 1024), color=(10, 20, 30)).save(square, format="PNG")
    real_square_data_uri = f"data:image/png;base64,{b64.b64encode(square.getvalue()).decode()}"

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = real_square_data_uri
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(_base_state(slides=[SLIDES[0]]))

    uploaded_bytes = sb.storage.from_.return_value.upload.call_args.kwargs["file"]
    uploaded_w, uploaded_h = Image.open(BytesIO(uploaded_bytes)).size
    assert uploaded_w * 9 == uploaded_h * 16, (
        f"{uploaded_w}x{uploaded_h} uploaded to storage is not exact 16:9"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gemini_failure_falls_back_to_gpt_image() -> None:
    """AC3 (Story 5-8b): Gemini "Nano Banana" (now primary) raises -> GPT
    Image 2 (now fallback) is tried and succeeds."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_gemini_primary = AsyncMock()
    mock_gemini_primary.generate.side_effect = RuntimeError("Gemini down")
    mock_gpt_fallback = AsyncMock()
    mock_gpt_fallback.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_primary,
        ),
        patch(
            "app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_gpt_fallback
        ),
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

    mock_gemini_primary = AsyncMock()
    mock_gemini_primary.generate.side_effect = RuntimeError("Gemini down")
    mock_gpt_fallback = AsyncMock()
    mock_gpt_fallback.generate.side_effect = RuntimeError("GPT Image down")
    sb = _mock_supabase()
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_primary,
        ),
        patch(
            "app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_gpt_fallback
        ),
        patch("app.core.cost_tracker.accumulate_cost", new=mock_accumulate),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert result["slide_images"][0] == {"slide_id": "slide_sec_0_0", "image_url": None}
    sb.storage.from_.return_value.upload.assert_not_called()
    mock_accumulate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_ceiling_over_skips_providers_entirely() -> None:
    """AC-3: cost ceiling already over -> image_url=None, zero calls to EITHER
    provider (not just the primary — a regression that skipped only the
    primary but still fell through to the fallback would pass a
    single-provider assertion here)."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_gemini_primary = AsyncMock()
    mock_gpt_fallback = AsyncMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_primary,
        ),
        patch(
            "app.providers.image.openai_image.OpenAIImageProvider", return_value=mock_gpt_fallback
        ),
    ):
        result = await image_generator_node(_base_state(slides=[SLIDES[0]]))

    assert result["slide_images"][0]["image_url"] is None
    mock_gemini_primary.generate.assert_not_called()
    mock_gpt_fallback.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_slide_entry_degrades_that_slide_only() -> None:
    """AC-11: a malformed slide entry (missing 'data'/'title'/'bullets')
    degrades JUST that slide, other slides still process normally."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    malformed = {
        "segment_id": "sec_bad",
        "data": {"slide_id": "slide_bad"},
    }  # missing title/bullets
    slides_in = [malformed, SLIDES[0]]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
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

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    unsafe_slide = {
        "segment_id": "sec_0",
        "data": {
            "slide_id": "../../etc/passwd",
            "title": "x",
            "bullets": ["y"],
            "image_url": None,
            "fallback_image_url": None,
        },
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
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
    mock_gemini_provider = AsyncMock()
    sb = _mock_supabase(node_outputs={"image_generator": cached_images})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
    ):
        result = await image_generator_node(_base_state())

    assert result["slide_images"] == cached_images
    mock_gemini_provider.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_run_writes_checkpoint() -> None:
    """AC-13: a successful run writes last_node + node_outputs."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
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

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
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
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        await image_generator_node(state)

    sent_prompt = mock_gemini_provider.generate.call_args.args[0]
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

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()
    sb.storage.from_.return_value.upload.side_effect = RuntimeError("Storage down")
    mock_accumulate = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
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

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = "not-a-real-data-uri"
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
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

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()

    bad_entry = {"segment_id": "sec_bad", "data": "oops-not-a-dict"}
    slides_in = [bad_entry, SLIDES[0]]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
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
            await image_generator_node(
                _base_state(lesson_id="../../etc/passwd", slides=[SLIDES[0]])
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_bullets_list_degrades_slide_without_calling_provider() -> None:
    """Review finding (Edge Case Hunter): an empty-but-present bullets list
    must be rejected like a malformed entry, not paid for."""
    from app.modules.content.pipeline.graph import image_generator_node

    mock_gemini_provider = AsyncMock()
    sb = _mock_supabase()

    empty_bullets_slide = {
        "segment_id": "sec_0",
        "data": {
            "slide_id": "slide_sec_0_0",
            "title": "Welcome",
            "bullets": [],
            "image_url": None,
            "fallback_image_url": None,
        },
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
    ):
        result = await image_generator_node(_base_state(slides=[empty_bullets_slide]))

    assert result["slide_images"][0]["image_url"] is None
    mock_gemini_provider.generate.assert_not_called()


# ---------------------------------------------------------------------------
# D132: bounded concurrent generation (D132-FIX-TRACKER.md)
# ---------------------------------------------------------------------------


def _slide(index: int, title: str = "Welcome") -> dict[str, Any]:
    return {
        "segment_id": f"sec_{index}",
        "data": {
            "slide_id": f"slide_sec_{index}_0",
            "title": title,
            "bullets": [f"Point {index}"],
            "image_url": None,
            "fallback_image_url": None,
        },
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slides_generate_concurrently_not_serially() -> None:
    """D132: images must actually generate concurrently, not one at a time.

    6 slides at a mocked 0.15s each: strictly serial execution would take
    ~0.9s; bounded concurrency at _IMAGE_GENERATION_CONCURRENCY (3) should
    take close to ceil(6/3) x 0.15s = ~0.3s. Asserting well under the serial
    total (not just "faster than serial") makes this a real overlap proof,
    not noise-sensitive to scheduler jitter.
    """
    from app.modules.content.pipeline.graph import (
        _IMAGE_GENERATION_CONCURRENCY,
        image_generator_node,
    )

    assert _IMAGE_GENERATION_CONCURRENCY == 3, (
        "test's timing margin assumes concurrency=3 — update if the constant changes"
    )

    n_slides = 6
    delay_s = 0.15
    slides_in = [_slide(i) for i in range(n_slides)]

    async def _slow_generate(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(delay_s)
        return _FAKE_DATA_URI

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.side_effect = _slow_generate
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        # `get_langfuse()` (via @traced_node) constructs a real process-wide
        # Langfuse singleton on its very FIRST call anywhere in the process,
        # which is slow (order of a second) — a fixed, one-time cost
        # unrelated to this node's own logic. Left unpatched, it dominates
        # elapsed time and makes this specific timing assertion depend on
        # whether some earlier test already paid that cost (flaky in
        # isolation, e.g. `pytest -k concurrently`, even though it happens to
        # pass inside the full file's run order). Patched here, like other
        # tests in this repo do (see test_provider_tracing_resilience.py),
        # so the measured elapsed time reflects only this node's own
        # concurrency behavior.
        patch("app.core.langfuse.get_langfuse", return_value=MagicMock()),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        start = time.monotonic()
        result = await image_generator_node(_base_state(slides=slides_in))
        elapsed = time.monotonic() - start

    assert len(result["slide_images"]) == n_slides
    serial_time = n_slides * delay_s  # 0.9s
    ideal_concurrent_time = 2 * delay_s  # ceil(6/3) x 0.15s = 0.3s
    assert elapsed < serial_time * 0.6, (
        f"elapsed={elapsed:.3f}s is not meaningfully faster than serial "
        f"execution ({serial_time:.3f}s would be strictly sequential; ideal "
        f"concurrent time is ~{ideal_concurrent_time:.3f}s) — slides may "
        "still be running one at a time"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrency_survives_a_slow_blocking_storage_upload() -> None:
    """D132 adversarial review finding: `supabase.storage` is storage3's SYNC
    client (blocking httpx under the hood, not async). Called directly on the
    event loop, one slide's upload would block every OTHER concurrently-
    scheduled slide's await for its own duration — defeating the concurrency
    this function exists to add, invisibly, since the OTHER new tests only
    put latency in the mocked `generate()` call, never in `upload()`.

    This test puts a REAL blocking `time.sleep` (not `asyncio.sleep`) inside
    the mocked `upload()` call — exactly what a real, slow network upload
    looks like to the event loop if it is never wrapped in
    `asyncio.to_thread`. Without that wrapping, this test fails (the sleep
    blocks the loop, serializing every slide's upload window); with it
    (the actual fix), slides still overlap and the timing bound holds.
    """
    import time as _time_module

    from app.modules.content.pipeline.graph import (
        _IMAGE_GENERATION_CONCURRENCY,
        image_generator_node,
    )

    n_slides = 6
    upload_delay_s = 0.15
    slides_in = [_slide(i) for i in range(n_slides)]

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.return_value = _FAKE_DATA_URI
    sb = _mock_supabase()
    # Blocking sleep — this callable runs inside asyncio.to_thread's worker
    # thread if (and only if) the fix wraps the upload call correctly; if
    # called directly on the event loop instead, this blocks it for real.
    sb.storage.from_.return_value.upload.side_effect = lambda **_kwargs: _time_module.sleep(
        upload_delay_s
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.langfuse.get_langfuse", return_value=MagicMock()),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        start = time.monotonic()
        result = await image_generator_node(_base_state(slides=slides_in))
        elapsed = time.monotonic() - start

    assert len(result["slide_images"]) == n_slides
    assert all(s["image_url"] is not None for s in result["slide_images"]), (
        "a slide degraded to image_url=None — the mocked upload should always succeed here"
    )
    serial_time = n_slides * upload_delay_s  # 0.9s if uploads serialize the loop
    assert elapsed < serial_time * 0.6, (
        f"elapsed={elapsed:.3f}s is not meaningfully faster than "
        f"{serial_time:.3f}s (fully-serialized-by-a-blocking-upload time) — "
        f"the Storage upload is blocking the event loop instead of running "
        f"in a thread, at concurrency={_IMAGE_GENERATION_CONCURRENCY}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_order_preserved_when_later_slide_finishes_first() -> None:
    """D132: slide_images_out stays index-matched to input `slides` even when
    a LATER slide's mocked generation completes before an EARLIER one's."""
    from app.modules.content.pipeline.graph import image_generator_node

    slide_slow = _slide(0, title="Slow")
    slide_fast = _slide(1, title="Fast")

    async def _generate(prompt: str, **kwargs: Any) -> str:
        if "Slow" in prompt:
            await asyncio.sleep(0.2)
        else:
            await asyncio.sleep(0.01)
        return _FAKE_DATA_URI

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.side_effect = _generate
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(_base_state(slides=[slide_slow, slide_fast]))

    images = result["slide_images"]
    assert len(images) == 2
    # Slide 1 ("Fast") finished generating well before slide 0 ("Slow") under
    # concurrency, but the output list must still reflect INPUT order.
    assert images[0]["slide_id"] == "slide_sec_0_0"
    assert images[0]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_0_0.png"
    assert images[1]["slide_id"] == "slide_sec_1_0"
    assert images[1]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_1_0.png"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_slide_failure_does_not_cancel_concurrent_siblings() -> None:
    """D132: under concurrency, one slide's exception (raised well after its
    concurrently-running siblings have started, from the upload step inside
    the per-slide try/except) must not cancel or otherwise affect any other
    slide's success — each slide's exception is caught INSIDE its own task,
    so asyncio.gather (no return_exceptions) never sees a raised exception,
    matching AC-11's pre-existing isolation guarantee under concurrency."""
    from app.modules.content.pipeline.graph import image_generator_node

    slide_fail = _slide(0, title="WillFail")
    slide_ok_1 = _slide(1, title="Ok1")
    slide_ok_2 = _slide(2, title="Ok2")

    async def _generate(prompt: str, **kwargs: Any) -> str:
        # All three slides start generating concurrently; the OK slides take
        # longer than the failing slide's own generate call so the failure
        # (at upload time, below) lands while OK-1/OK-2 are still in flight.
        await asyncio.sleep(0.05 if "WillFail" in prompt else 0.15)
        return _FAKE_DATA_URI

    mock_gemini_provider = AsyncMock()
    mock_gemini_provider.generate.side_effect = _generate
    sb = _mock_supabase()

    def _upload_side_effect(*, path: str, file: bytes, file_options: dict[str, Any]) -> MagicMock:
        if "slide_sec_0_0" in path:
            raise RuntimeError("storage down for this slide only")
        return MagicMock()

    sb.storage.from_.return_value.upload.side_effect = _upload_side_effect

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.providers.image.nano_banana.NanoBananaProvider",
            return_value=mock_gemini_provider,
        ),
        patch("app.core.cost_tracker.accumulate_cost", new_callable=AsyncMock),
    ):
        result = await image_generator_node(
            _base_state(slides=[slide_fail, slide_ok_1, slide_ok_2])
        )

    images = result["slide_images"]
    assert len(images) == 3, "the whole node must not crash or drop slides"
    # Failing slide degrades exactly as it always has: image_url=None.
    assert images[0]["slide_id"] == "slide_sec_0_0"
    assert images[0]["image_url"] is None
    # Both concurrently-running siblings still complete successfully — proof
    # that one task's exception did not cancel or corrupt the others.
    assert images[1]["slide_id"] == "slide_sec_1_0"
    assert images[1]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_1_0.png"
    assert images[2]["slide_id"] == "slide_sec_2_0"
    assert images[2]["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_2_0.png"
