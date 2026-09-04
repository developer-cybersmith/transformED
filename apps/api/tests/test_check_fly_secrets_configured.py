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

# __file__ = <root>/apps/api/tests/test_check_fly_secrets_configured.py
# → parents[3] is the repo root (same layout as test_ws_load_test.py).
_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[3] / "scripts" / "check_fly_secrets_configured.py"
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
    has once (that's the exact class of bug D146 surfaced one layer up)."""
    fields = required_settings_fields()
    # Spot-check real, currently-required Settings fields (app/config.py) —
    # if config.py ever drops these to optional, this test must be updated
    # deliberately, not silently pass for the wrong reason.
    assert "SUPABASE_URL" in fields
    assert "OPENAI_API_KEY" in fields
    assert "SUPABASE_JWT_SECRET" in fields
    # A field with a default (e.g. redis_url has one) must NOT appear —
    # proves this filters on is_required(), not just "every field".
    assert "REDIS_URL" not in fields


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
    discipline for exactly this drift class."""
    rate_limit_source = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "core" / "rate_limit.py"
    ).read_text(encoding="utf-8")
    assert "RATE_LIMIT_STORAGE_URL" in rate_limit_source


# ---------------------------------------------------------------------------
# _fetch_configured_secret_names — subprocess boundary, always mocked
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_configured_secret_names_parses_real_flyctl_json_shape() -> None:
    fake_result = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [
                {"Name": "SUPABASE_URL", "Digest": "abc123", "CreatedAt": "2026-08-01T00:00:00Z"},
                {"Name": "OPENAI_API_KEY", "Digest": "def456", "CreatedAt": "2026-08-01T00:00:00Z"},
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
