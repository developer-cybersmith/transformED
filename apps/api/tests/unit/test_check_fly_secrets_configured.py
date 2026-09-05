"""D150 — deploy-time verification that every secret this app's startup guards
require is actually present on the target Fly app, closing the residual gap
named in D146's own disposition: nothing previously diffed "secrets a story's
code depends on" against "secrets actually deployed" — D49's guard was
correct, the deployed Fly app just never had `RATE_LIMIT_STORAGE_URL` set,
and nothing caught that before Fly crash-looped in production for ~3 hours.

The script lives under ``scripts/`` (not a package), so it is loaded by file
path via importlib — mirrors ``test_ws_load_test.py``'s existing pattern for
``scripts/ws_load_test.py``.

``@pytest.mark.unit`` — no real ``flyctl`` process or network call anywhere
in this file; ``subprocess.run`` is mocked throughout.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings

# __file__ = <root>/apps/api/tests/unit/test_check_fly_secrets_configured.py
# → parents[4] is the repo root.
#
# [Review][Patch] moved here from apps/api/tests/ (2026-09-04): the root-level
# location was never actually gating CI -- ci.yml's only gating step is
# `pytest tests/unit tests/integration`, and root-level tests only run in the
# `continue-on-error: true` advisory step (the same gap ci.yml's own comments
# already document, D24, for a different file). Confirmed directly, not
# assumed. test_rate_limit_storage_guard.py in this same directory is the
# correct precedent this file should have followed originally.
_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[4] / "scripts" / "check_fly_secrets_configured.py"
)
_spec = importlib.util.spec_from_file_location("check_fly_secrets_configured", _SCRIPT)
assert _spec and _spec.loader
check_fly_secrets_configured = importlib.util.module_from_spec(_spec)
sys.modules["check_fly_secrets_configured"] = check_fly_secrets_configured
_spec.loader.exec_module(check_fly_secrets_configured)

list_missing_secrets = check_fly_secrets_configured.list_missing_secrets
required_settings_fields = check_fly_secrets_configured.required_settings_fields
required_secrets = check_fly_secrets_configured.required_secrets
_fetch_configured_secret_names = check_fly_secrets_configured._fetch_configured_secret_names
main = check_fly_secrets_configured.main


# ---------------------------------------------------------------------------
# list_missing_secrets — pure diff logic, no I/O
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_missing_secrets_none_configured_all_missing() -> None:
    required = {"SUPABASE_URL": "x", "OPENAI_API_KEY": "y"}
    assert list_missing_secrets(required, set()) == ["OPENAI_API_KEY", "SUPABASE_URL"]


@pytest.mark.unit
def test_list_missing_secrets_all_configured_none_missing() -> None:
    required = {"SUPABASE_URL": "x", "OPENAI_API_KEY": "y"}
    configured = {"SUPABASE_URL", "OPENAI_API_KEY", "SOME_OTHER_SECRET_NOT_REQUIRED"}
    assert list_missing_secrets(required, configured) == []


@pytest.mark.unit
def test_list_missing_secrets_partial_overlap_sorted() -> None:
    required = {"SUPABASE_URL": "x", "OPENAI_API_KEY": "y", "RATE_LIMIT_STORAGE_URL": "z"}
    configured = {"SUPABASE_URL"}
    assert list_missing_secrets(required, configured) == [
        "OPENAI_API_KEY",
        "RATE_LIMIT_STORAGE_URL",
    ]


# ---------------------------------------------------------------------------
# required_settings_fields / required_secrets — anti-drift, live introspection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_required_settings_fields_is_derived_live_not_a_fixed_list() -> None:
    """Proves this reads app.config.Settings for real, rather than a hand-typed
    list that could silently drift the way the underlying app config already
    has once (that's the exact class of bug D146 surfaced one layer up).

    [Review][Patch] rewritten 2026-09-04: the original version only
    spot-checked 4 hardcoded field names, which would pass unchanged even if
    required_settings_fields() were replaced with a hand-copied literal set
    -- the exact drift class AC1/AC5 exist to prevent, and it wouldn't have
    caught it. This version independently recomputes the expected set from
    Settings.model_fields (the same source, but a second, independent call
    site) and asserts full equality against the script's real output."""
    expected = {
        name.upper() for name, field in Settings.model_fields.items() if field.is_required()
    }
    assert expected, "test precondition failed: Settings has zero required fields"
    assert required_settings_fields() == expected


@pytest.mark.unit
def test_required_secrets_includes_rate_limit_storage_url_guard_entry() -> None:
    """RATE_LIMIT_STORAGE_URL has a non-raising pydantic default (memory://),
    so required_settings_fields() alone would never catch it — this is
    D49's guard-enforced case, the one that actually caused D146."""
    manifest = required_secrets()
    assert "RATE_LIMIT_STORAGE_URL" in manifest


@pytest.mark.unit
def test_rate_limit_storage_url_name_still_present_in_the_real_guard_source() -> None:
    """Source-scan anti-drift test (Story BR-5 AC5): if a future refactor
    renames RATE_LIMIT_STORAGE_URL inside app.core.rate_limit's guard without
    updating this script's hand-listed _GUARD_ENFORCED_SECRETS entry, this
    must redden — mirrors this repo's established `# SYNC:`-comment
    discipline for exactly this drift class.

    [Review][Patch] narrowed 2026-09-04: a whole-file substring check would
    pass identically whether the name lives in real enforcement code, a
    stale comment, or a leftover docstring after a rename -- scoped to the
    actual enforcement region (the guard function's body + the module-level
    storage-URI constant it and `limiter` both read) instead."""
    rate_limit_source = (
        pathlib.Path(__file__).resolve().parents[2] / "app" / "core" / "rate_limit.py"
    ).read_text(encoding="utf-8")
    guard_start = rate_limit_source.index("def assert_rate_limit_storage_configured")
    guard_region = rate_limit_source[guard_start:]
    assert "RATE_LIMIT_STORAGE_URL" in guard_region, (
        "RATE_LIMIT_STORAGE_URL must appear inside assert_rate_limit_storage_configured's own "
        "body (its docstring/error message), not just somewhere else in the file"
    )
    constant_line = next(
        line for line in rate_limit_source.splitlines() if "_RATE_LIMIT_STORAGE_URI = " in line
    )
    assert "RATE_LIMIT_STORAGE_URL" in constant_line, (
        "the module-level storage-URI constant (read by both `limiter` and the guard) must "
        "still be sourced from RATE_LIMIT_STORAGE_URL"
    )


# ---------------------------------------------------------------------------
# _fetch_configured_secret_names — subprocess boundary, always mocked
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_configured_secret_names_parses_real_flyctl_json_shape() -> None:
    fake_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [
                {"name": "SUPABASE_URL", "digest": "abc123", "status": "Deployed"},
                {"name": "OPENAI_API_KEY", "digest": "def456", "status": "Deployed"},
            ]
        ),
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        names = _fetch_configured_secret_names("hie-api")
    assert names == {"SUPABASE_URL", "OPENAI_API_KEY"}
    mock_run.assert_called_once()
    called_args = mock_run.call_args.args[0]
    assert called_args == ["flyctl", "secrets", "list", "--app", "hie-api", "--json"]


@pytest.mark.unit
def test_fetch_configured_secret_names_raises_loud_on_nonzero_exit() -> None:
    """The D146 failure shape one layer up: a check that silently reports
    'fine' when it actually couldn't verify anything is the same class of
    bug as the guard that fired correctly but nobody watched. This must
    raise, never return an empty/partial set that main() could mistake for
    'nothing missing'."""
    fake_result = MagicMock(returncode=1, stdout="", stderr="Error: could not authenticate")
    with patch("subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match=r"flyctl secrets list"):
            _fetch_configured_secret_names("hie-api")


@pytest.mark.unit
def test_fetch_configured_secret_names_raises_loud_on_unparseable_json() -> None:
    fake_result = MagicMock(returncode=0, stdout="not json at all", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match=r"unparseable"):
            _fetch_configured_secret_names("hie-api")


@pytest.mark.unit
def test_fetch_configured_secret_names_raises_loud_when_flyctl_binary_is_missing() -> None:
    """Real bug found live while dev-verifying this script (flyctl not
    installed on this machine): `subprocess.run` raises `FileNotFoundError`
    directly when the executable itself can't be found -- it never reaches
    a `returncode != 0` check, because the process is never launched. The
    original implementation let this propagate as a raw, uncaught traceback
    past main()'s `except RuntimeError` entirely — the exact 'silent pass /
    unclean failure' class AC2 exists to rule out, just via a crash instead
    of a false OK. Must raise the same clean RuntimeError as every other
    failure mode."""
    with patch("subprocess.run", side_effect=FileNotFoundError("[WinError 2] not found")):
        with pytest.raises(RuntimeError, match=r"flyctl.*not found"):
            _fetch_configured_secret_names("hie-api")


@pytest.mark.unit
def test_fetch_configured_secret_names_raises_loud_when_flyctl_is_not_executable() -> None:
    """[Review][Patch]: the fix above only caught FileNotFoundError, not the
    broader OSError family subprocess.run's launch path can raise -- e.g. a
    `flyctl` present on PATH but not executable (a PermissionError, a sibling
    of FileNotFoundError, not a subclass -- the original except clause never
    caught it). Same 'crash instead of clean RuntimeError' consequence,
    found by 2 independent review layers (Blind Hunter, Edge Case Hunter)."""
    with patch("subprocess.run", side_effect=PermissionError("[Errno 13] Permission denied")):
        with pytest.raises(RuntimeError, match=r"flyctl"):
            _fetch_configured_secret_names("hie-api")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "stdout"),
    [
        ("object instead of array", json.dumps({"error": "app not found"})),
        ("list of dicts missing name key", json.dumps([{"digest": "abc123"}])),
        ("literal null", "null"),
        ("list of bare strings, not objects", json.dumps(["SUPABASE_URL", "OPENAI_API_KEY"])),
    ],
)
def test_fetch_configured_secret_names_raises_loud_on_valid_json_wrong_shape(
    label: str, stdout: str
) -> None:
    """[Review][Patch]: `flyctl secrets list --json` returning syntactically
    VALID but wrongly-shaped JSON (not a list of {"name": ...} objects) used
    to raise an uncaught KeyError/TypeError past main()'s `except
    RuntimeError` entirely -- json.loads succeeds, so the pre-existing
    JSONDecodeError handler never fires. Reproduced live by the Test Coverage
    review layer with these exact 3 payloads (plus a 4th here); independently
    found by Edge Case Hunter and Blind Hunter. Must raise the same clean
    RuntimeError as every other failure mode, not crash."""
    fake_result = MagicMock(returncode=0, stdout=stdout, stderr="")
    with patch("subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match=r"unexpected shape"):
            _fetch_configured_secret_names("hie-api")


@pytest.mark.unit
def test_fetch_configured_secret_names_raises_loud_on_timeout() -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="flyctl", timeout=30),
    ):
        with pytest.raises(RuntimeError, match=r"timed out"):
            _fetch_configured_secret_names("hie-api")


# ---------------------------------------------------------------------------
# main() — exit codes are the real deploy-blocking contract (AC2/AC3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_main_exits_zero_when_everything_required_is_present() -> None:
    all_present = set(required_secrets().keys()) | {"UNRELATED_EXTRA_SECRET"}
    with patch.object(sys, "argv", ["check_fly_secrets_configured.py", "--app", "hie-api"]):
        with patch(
            "check_fly_secrets_configured._fetch_configured_secret_names",
            return_value=all_present,
        ):
            assert main() == 0


@pytest.mark.unit
def test_main_exits_nonzero_when_a_required_secret_is_missing() -> None:
    with patch.object(sys, "argv", ["check_fly_secrets_configured.py", "--app", "hie-api"]):
        with patch(
            "check_fly_secrets_configured._fetch_configured_secret_names",
            return_value=set(),
        ):
            assert main() != 0


@pytest.mark.unit
def test_main_exits_nonzero_never_zero_when_the_check_itself_cannot_run() -> None:
    """'Couldn't verify' must never be reported as 'verified OK' (AC2) — the
    exact class of silent-pass this story exists to prevent."""
    with patch.object(sys, "argv", ["check_fly_secrets_configured.py", "--app", "hie-api"]):
        with patch(
            "check_fly_secrets_configured._fetch_configured_secret_names",
            side_effect=RuntimeError("flyctl secrets list failed (exit 1): auth error"),
        ):
            assert main() != 0


@pytest.mark.unit
def test_main_prints_a_clear_confirmation_line_on_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """[Review][Patch] AC2's printed-output half was previously unasserted --
    only exit codes were tested. AC2 literally requires 'a clear confirmation
    line' on success."""
    all_present = set(required_secrets().keys()) | {"UNRELATED_EXTRA_SECRET"}
    with patch.object(sys, "argv", ["check_fly_secrets_configured.py", "--app", "hie-api"]):
        with patch(
            "check_fly_secrets_configured._fetch_configured_secret_names",
            return_value=all_present,
        ):
            main()
    captured = capsys.readouterr()
    assert "OK" in captured.out
    assert "hie-api" in captured.out


@pytest.mark.unit
def test_main_prints_every_missing_secret_name_and_its_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """[Review][Patch] AC2 literally requires printing 'every missing secret's
    name plus which guard/field requires it' -- verify the real stdout/stderr
    content, not just that main() returned non-zero."""
    with patch.object(sys, "argv", ["check_fly_secrets_configured.py", "--app", "hie-api"]):
        with patch(
            "check_fly_secrets_configured._fetch_configured_secret_names",
            return_value=set(),
        ):
            main()
    captured = capsys.readouterr()
    for name, reason in required_secrets().items():
        assert name in captured.err
        assert reason in captured.err


@pytest.mark.unit
def test_main_exits_nonzero_not_uncaught_when_required_secrets_itself_fails() -> None:
    """[Review][Patch]: required_secrets() (imports app.config.Settings) was
    called in main() entirely outside the try/except RuntimeError block --
    any future failure there (e.g. a config.py import-time error) crashed
    uncaught instead of producing AC2's mandated clean exit 1. Found by Edge
    Case Hunter."""
    with patch.object(sys, "argv", ["check_fly_secrets_configured.py", "--app", "hie-api"]):
        with patch(
            "check_fly_secrets_configured.required_secrets",
            side_effect=ImportError("simulated app.config import failure"),
        ):
            assert main() != 0


@pytest.mark.unit
def test_no_required_settings_field_currently_uses_a_pydantic_alias() -> None:
    """[Review][Patch] required_settings_fields()'s `name.upper()` derivation
    assumes the attribute name IS the env var name -- true today, but a
    future Settings field declared with `alias=`/`validation_alias=` would
    silently break this (the script would check for the wrong name,
    reporting a correctly-configured secret as missing). No field uses one
    today; this guard fails loud in CI the day one is added without this
    script being updated to handle it, rather than silently misreporting."""
    for name, field in Settings.model_fields.items():
        if not field.is_required():
            continue
        assert field.alias is None, (
            f"Settings field {name!r} now has alias={field.alias!r} -- "
            "required_settings_fields()'s name.upper() derivation no longer matches the real "
            "env var name pydantic-settings reads; update check_fly_secrets_configured.py to "
            "prefer the alias before this can pass"
        )
