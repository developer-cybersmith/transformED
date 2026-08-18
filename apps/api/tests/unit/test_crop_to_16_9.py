"""D118 follow-up (2026-08-17): `_crop_to_16_9` guarantees every uploaded
slide image is an EXACT 16:9, regardless of which provider generated it or
what pixel size it actually returned.

D122 (2026-08-18) migrated the primary provider from gpt-image-1-mini to
gpt-image-2 and moved `_SLIDE_IMAGE_SIZE` to "1280x720" — a size gpt-image-2
supports natively via custom dimensions, and which happens to already be
EXACT 16:9 (1280*9 == 720*16). So on the primary path today, `_crop_to_16_9`
is provably a no-op (see `test_crop_to_16_9_is_a_true_no_op_on_the_real_
production_size` below) — it earns its keep only as a safety net for the
fallback provider (Imagen, D121, presently non-functional) or any future
provider that doesn't guarantee exact 16:9 natively. Confirmed by direct
computation before D122 existed: gpt-image-1-mini's real landscape preset,
"1536x1024" (D120 — corrected from an earlier, WRONG "1792x1024" assumption)
was exactly 3:2 (1.5:1), NOT 16:9 -- about 15.6% narrower; that history is
what `test_a_non_16_9_landscape_image_is_still_correctly_cropped` below
exercises, generically, so the crop machinery itself stays proven even
though the primary path no longer needs it.

This function is provider-agnostic (introspects actual image bytes rather
than trusting either provider's declared size, which is exactly what caught
the D120 mistake in the first place) and pure (bytes in, bytes out, no I/O).

The primary-size test below imports `_SLIDE_IMAGE_SIZE` from graph.py
directly, rather than hardcoding its value a second time, specifically so
this suite cannot silently drift out of sync with the real constant again
the way its
own numbers already did once.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (200, 50, 50)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _ratio(image_bytes: bytes) -> tuple[int, int]:
    img = Image.open(BytesIO(image_bytes))
    return img.size


@pytest.mark.unit
def test_the_real_production_size_is_exact_16_9() -> None:
    """D122's whole payoff: `_SLIDE_IMAGE_SIZE` (gpt-image-2, "1280x720")
    must be EXACT 16:9 on its own, derived from the real constant rather
    than a hardcoded literal, so this can't silently go stale the way the
    constant itself already did twice (D118 -> D120 -> D122). If this ever
    regresses (someone changes the constant to a non-16:9 size again), this
    is the test that should catch it first — before falling back to relying
    on the crop step to paper over it."""
    from app.modules.content.pipeline.graph import _SLIDE_IMAGE_SIZE

    w_str, h_str = _SLIDE_IMAGE_SIZE.split("x")
    src_w, src_h = int(w_str), int(h_str)
    assert src_w * 9 == src_h * 16, (
        f"_SLIDE_IMAGE_SIZE={_SLIDE_IMAGE_SIZE!r} is NOT exact 16:9 -- "
        "the primary provider no longer guarantees the ratio natively"
    )


@pytest.mark.unit
def test_crop_to_16_9_is_a_true_no_op_on_the_real_production_size() -> None:
    """Proves `_crop_to_16_9` does NOT touch (re-encode, re-compress, or
    even open via PIL beyond the size check) the actual bytes GPT Image 2
    returns today -- the crop machinery below exists purely as a safety net
    for the fallback provider now, not for the primary path."""
    from app.modules.content.pipeline.graph import _SLIDE_IMAGE_SIZE, _crop_to_16_9

    w_str, h_str = _SLIDE_IMAGE_SIZE.split("x")
    original = _png_bytes(int(w_str), int(h_str))
    assert _crop_to_16_9(original) == original


@pytest.mark.unit
def test_a_non_16_9_landscape_image_is_still_correctly_cropped() -> None:
    """The crop machinery must still work correctly for whatever the
    FALLBACK provider (or any future non-gpt-image-2 provider) returns --
    proven here against a generic mismatched size, not tied to any specific
    provider's current constant (which is exactly what made the previous
    version of this test fragile: D120 had to rewrite it once already)."""
    from app.modules.content.pipeline.graph import _crop_to_16_9

    src_w, src_h = 1536, 1024  # 3:2 -- gpt-image-1-mini's old real size
    out = _crop_to_16_9(_png_bytes(src_w, src_h))
    w, h = _ratio(out)
    assert w * 9 == h * 16, f"{w}x{h} is not exact 16:9"
    # A minimal crop, not a redo: width untouched, height trimmed.
    assert w == src_w
    assert h == round(src_w * 9 / 16)


@pytest.mark.unit
def test_an_already_exact_16_9_image_is_returned_byte_identical() -> None:
    """No-op path: must not re-encode (and therefore possibly re-compress or
    change) an image that is already exactly 16:9."""
    from app.modules.content.pipeline.graph import _crop_to_16_9

    original = _png_bytes(1920, 1080)  # exact 16:9
    out = _crop_to_16_9(original)
    assert out == original


@pytest.mark.unit
def test_a_square_image_narrower_than_16_9_is_cropped_on_height_not_width() -> None:
    """A square image (e.g. Imagen's default 1:1 fallback, or the OLD D118
    bug's output) is relatively TALLER than 16:9 for its width (1:1 = 1.0 <
    16:9 = 1.778) -- must crop HEIGHT, preserving the full width, since there
    is no width to gain. Confirmed by direct computation: 1024x1024 ->
    1024x576 (1024*9/16 = 576), not the reverse."""
    from app.modules.content.pipeline.graph import _crop_to_16_9

    out = _crop_to_16_9(_png_bytes(1024, 1024))  # square
    w, h = _ratio(out)
    assert w * 9 == h * 16
    assert w == 1024  # width preserved
    assert h == 576  # height cropped: 1024 * 9 / 16 = 576


@pytest.mark.unit
def test_corrupt_bytes_degrade_to_the_original_input_not_a_raise() -> None:
    """Never let a cosmetic normalization step fail an otherwise-good image
    (AC-11's spirit, applied one level more conservatively)."""
    from app.modules.content.pipeline.graph import _crop_to_16_9

    garbage = b"this is not a png"
    assert _crop_to_16_9(garbage) == garbage


@pytest.mark.unit
def test_empty_bytes_degrade_to_the_original_input_not_a_raise() -> None:
    from app.modules.content.pipeline.graph import _crop_to_16_9

    assert _crop_to_16_9(b"") == b""
