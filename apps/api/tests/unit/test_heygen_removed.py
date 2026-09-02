"""Guard (D141): HeyGen must not reappear.

`HeyGenAvatarProvider` was dead, unwired code — no pipeline node ever
instantiated it — removed as a deliberate cleanup, not a behavior change (see
`docs/DEFECT-REGISTER.md` D141). This guard is the actual RED/GREEN pivot for
that deletion: it fails while the code still exists (proving the guard is
real, not vacuous) and passes once it is gone, so a future re-introduction
(a copy-pasted provider file, a re-added `AvatarProvider` ABC) fails CI
instead of silently reappearing.

Source-scan only, not an import-based check: importing
`app.providers.avatar.heygen` after the file is deleted would itself raise
`ModuleNotFoundError`, which proves the file is gone but not that nothing
ELSE reintroduced the class under a different path. Scanning every `.py`
file's text catches either.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / "app"


def _grep_app(needle: str) -> list[str]:
    """Every file under app/ whose text contains *needle*, relative paths."""
    hits: list[str] = []
    for py_file in _APP_DIR.rglob("*.py"):
        if needle in py_file.read_text(encoding="utf-8"):
            hits.append(py_file.relative_to(_APP_DIR).as_posix())
    return hits


@pytest.mark.unit
def test_heygen_avatar_provider_file_does_not_exist() -> None:
    assert not (_APP_DIR / "providers" / "avatar" / "heygen.py").exists(), (
        "providers/avatar/heygen.py must not exist — HeyGen was removed as "
        "dead/unwired code (D141), not merely deprecated"
    )


@pytest.mark.unit
def test_heygen_avatar_provider_class_does_not_appear_anywhere() -> None:
    hits = _grep_app("HeyGenAvatarProvider")
    assert not hits, f"HeyGenAvatarProvider reintroduced in: {hits} — see D141"


@pytest.mark.unit
def test_avatar_provider_abc_does_not_appear_anywhere() -> None:
    """AvatarProvider (the abstract interface HeyGenAvatarProvider
    implemented) was removed alongside it — no other provider implements
    it, so it has no reason to exist."""
    hits = _grep_app("class AvatarProvider")
    assert not hits, f"AvatarProvider ABC reintroduced in: {hits} — see D141"


@pytest.mark.unit
def test_heygen_api_key_setting_does_not_exist() -> None:
    hits = _grep_app("heygen_api_key")
    assert not hits, f"heygen_api_key config field reintroduced in: {hits} — see D141"


@pytest.mark.unit
def test_avatar_clips_bucket_is_no_longer_required() -> None:
    """The bucket itself is NOT retired from the frozen migration (D141) —
    only the requirement that the app check for it at startup."""
    from app.core.storage import REQUIRED_BUCKETS

    assert "avatar-clips" not in REQUIRED_BUCKETS, (
        "avatar-clips should no longer be in REQUIRED_BUCKETS — nothing "
        "references it since HeyGen was removed (D141)"
    )
