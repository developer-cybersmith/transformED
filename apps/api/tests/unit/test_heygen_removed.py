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

Review findings (both fixed here, both worth recording):
- The class-name checks were originally a plain substring search (`"class
  AvatarProvider" in source`), which a purely cosmetic reformat (`class
  AvatarProvider(ABC):` with different spacing) could evade. Replaced with a
  real `ast.parse` + `ClassDef.name` check — the same class of technique
  `test_unbounded_queries.py`/`test_provider_call_site_guard.py` already use
  in this repo, robust to whitespace. Known, accepted remaining limitation
  (same honesty those other guards state about their own scope): a
  deliberate RENAME (`class HeyGenBackend(ABC)` instead of `AvatarProvider`)
  still evades any name-based check — that requires recognizing the class is
  *functionally* the same dead feature, not just spelled the same, which is
  out of proportion to what a source-scan guard exists to catch (accidental
  reintroduction of the exact removed code, not a deliberately disguised
  reintroduction).
- The `heygen_api_key` config-field check was a case-sensitive substring
  search, but `Settings.model_config` sets `case_sensitive=False` — a
  reintroduced field spelled `Heygen_Api_Key` binds from `HEYGEN_API_KEY` at
  runtime exactly as before, fully functional, while evading a case-sensitive
  grep. Fixed: search the lowercased source text.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / "app"


def _grep_app(needle: str, *, case_insensitive: bool = False) -> list[str]:
    """Every file under app/ whose text contains *needle*, relative paths."""
    hits: list[str] = []
    for py_file in _APP_DIR.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        haystack = source.lower() if case_insensitive else source
        target = needle.lower() if case_insensitive else needle
        if target in haystack:
            hits.append(py_file.relative_to(_APP_DIR).as_posix())
    return hits


def _classes_named(name: str) -> list[str]:
    """Every file under app/ that defines a class named *name*, via AST —
    robust to whitespace/formatting, unlike a substring search."""
    hits: list[str] = []
    for py_file in _APP_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.ClassDef) and node.name == name for node in ast.walk(tree)):
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
    hits = _classes_named("HeyGenAvatarProvider")
    assert not hits, f"HeyGenAvatarProvider reintroduced in: {hits} — see D141"


@pytest.mark.unit
def test_avatar_provider_abc_does_not_appear_anywhere() -> None:
    """AvatarProvider (the abstract interface HeyGenAvatarProvider
    implemented) was removed alongside it — no other provider implements
    it, so it has no reason to exist."""
    hits = _classes_named("AvatarProvider")
    assert not hits, f"AvatarProvider ABC reintroduced in: {hits} — see D141"


@pytest.mark.unit
def test_scanner_detects_a_reformatted_planted_class() -> None:
    """Proves the AST-based detector actually catches what the original
    substring version missed: a class matching by NAME regardless of
    whitespace/formatting around it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        planted = Path(tmp_dir) / "planted.py"
        planted.write_text("class  AvatarProvider(  ):\n    pass\n", encoding="utf-8")
        tree = ast.parse(planted.read_text(encoding="utf-8"))
        assert any(
            isinstance(node, ast.ClassDef) and node.name == "AvatarProvider"
            for node in ast.walk(tree)
        ), "AST-based detection must find a class by name regardless of spacing"


@pytest.mark.unit
def test_heygen_api_key_setting_does_not_exist() -> None:
    """Case-insensitive: Settings.model_config sets case_sensitive=False, so
    a reintroduced field spelled with different casing (e.g. Heygen_Api_Key)
    would still bind from HEYGEN_API_KEY at runtime — a case-sensitive grep
    would miss it while the regression was fully functional."""
    hits = _grep_app("heygen_api_key", case_insensitive=True)
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
