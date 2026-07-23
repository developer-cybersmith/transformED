"""
Unit tests for app.core.storage.sign_storage_path — the shared Supabase
Storage signing helper used by both media/router.py and content/router.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_supabase(create_signed_url_return: object = None, raises: bool = False) -> MagicMock:
    sb = MagicMock()
    bucket = sb.storage.from_.return_value
    if raises:
        bucket.create_signed_url.side_effect = RuntimeError("boom")
    else:
        bucket.create_signed_url.return_value = create_signed_url_return
    return sb


@pytest.mark.unit
def test_sign_storage_path_success() -> None:
    from app.core.storage import sign_storage_path

    sb = _make_supabase({"signedURL": "https://example.com/signed?token=abc"})
    result = sign_storage_path(sb, "lesson-audio", "lid/seg.mp3", 1800)
    assert result == "https://example.com/signed?token=abc"
    sb.storage.from_.assert_called_once_with("lesson-audio")
    sb.storage.from_.return_value.create_signed_url.assert_called_once_with("lid/seg.mp3", 1800)


@pytest.mark.unit
def test_sign_storage_path_default_expires_in() -> None:
    from app.core.storage import sign_storage_path

    sb = _make_supabase({"signedURL": "https://example.com/signed"})
    sign_storage_path(sb, "lesson-images", "lid/slide.png")
    sb.storage.from_.return_value.create_signed_url.assert_called_once_with("lid/slide.png", 3600)


@pytest.mark.unit
def test_sign_storage_path_none_on_raise() -> None:
    from app.core.storage import sign_storage_path

    sb = _make_supabase(raises=True)
    assert sign_storage_path(sb, "lesson-audio", "lid/seg.mp3") is None


@pytest.mark.unit
def test_sign_storage_path_none_on_missing_key() -> None:
    from app.core.storage import sign_storage_path

    sb = _make_supabase({})
    assert sign_storage_path(sb, "lesson-audio", "lid/seg.mp3") is None


@pytest.mark.unit
def test_sign_storage_path_none_on_none_value() -> None:
    from app.core.storage import sign_storage_path

    sb = _make_supabase({"signedURL": None})
    assert sign_storage_path(sb, "lesson-audio", "lid/seg.mp3") is None
