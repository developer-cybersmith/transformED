"""D150 — deploy-time verification that every secret this app's startup
guards require is actually present in the target Fly app's secret store.

Closes the residual gap named in D146's own disposition: D49's
``assert_rate_limit_storage_configured()`` (and pydantic-settings' own
required-field validation) correctly fail loud if a required env var is
unset -- but nothing previously diffed "secrets the code requires" against
"secrets actually deployed," so a missing secret was only discovered by
Fly crash-looping in production for ~3 hours (2026-09-03) before anyone
noticed, well past Fly's `max_retries: 10` silent give-up.

Two independent, anti-drift sources feed the required-secrets manifest:
  1. Every pydantic `Settings` field with no default (`Settings.model_fields`,
     introspected live -- never hand-copied, so a new required Settings
     field is automatically covered without touching this file).
  2. Custom fail-loud startup guards whose gated env var isn't a required
     Settings field (`RATE_LIMIT_STORAGE_URL` has a `memory://` default, so
     pydantic never flags it -- only `assert_rate_limit_storage_configured`
     does). Hand-listed here, backed by
     `test_check_fly_secrets_configured.py`'s source-scan test asserting the
     name still appears in that guard's own module, so the two can't
     silently drift apart.

Usage:
    python scripts/check_fly_secrets_configured.py --app hie-api
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Make `app.config` importable when run from the repo root (its normal
# invocation, e.g. from .github/workflows/deploy.yml).
_API_ROOT = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))


# Custom fail-loud startup guards gating an env var pydantic-settings does
# NOT already require (i.e. the Settings field has a non-raising default).
# name -> why it's here / which guard enforces it.
_GUARD_ENFORCED_SECRETS: dict[str, str] = {
    "RATE_LIMIT_STORAGE_URL": (
        "app.core.rate_limit.assert_rate_limit_storage_configured (D49/D146) -- "
        "defaults to memory:// so pydantic never flags it, but the app refuses "
        "to boot outside debug mode if it isn't set to real shared storage."
    ),
}


def required_settings_fields() -> set[str]:
    """Every pydantic Settings field with no default, as its env var name.

    Introspected live from `app.config.Settings` -- never hand-copied -- so a
    story that adds a new required Settings field is automatically covered
    the next time this runs, with no separate manifest to remember to update.
    """
    from app.config import Settings

    return {
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.is_required()
    }


def required_secrets() -> dict[str, str]:
    """Full manifest: pydantic-required fields + custom-guard-enforced vars."""
    manifest = {
        name: "required Settings field (app.config.Settings, no default)"
        for name in required_settings_fields()
    }
    manifest.update(_GUARD_ENFORCED_SECRETS)
    return manifest


def list_missing_secrets(
    required: dict[str, str], configured_names: set[str]
) -> list[str]:
    """Pure diff -- required names not present in configured_names, sorted."""
    return sorted(name for name in required if name not in configured_names)


def _fetch_configured_secret_names(app: str) -> set[str]:
    """Real secret NAMES currently set on the Fly app.

    `flyctl secrets list` never exposes values -- which is exactly what this
    check needs: presence-only, so no secret material ever touches CI logs.
    """
    try:
        result = subprocess.run(
            ["flyctl", "secrets", "list", "--app", app, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,  # non-zero exit is handled explicitly below, not raised
        )
    except FileNotFoundError as exc:
        # `flyctl` isn't on PATH at all -- a plain non-zero exit never
        # happens because the process was never launched. Caught here so
        # this surfaces as the same clean, actionable RuntimeError as every
        # other failure mode, not a raw traceback main()'s `except
        # RuntimeError` wouldn't catch (D150's own AC2: "never a silent
        # pass," which includes never degrading to an unhandled crash).
        raise RuntimeError(f"`flyctl` executable not found on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"`flyctl secrets list --app {app}` timed out after 30s: {exc}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"`flyctl secrets list --app {app}` failed (exit {result.returncode}): "
            f"{result.stderr.strip()}. Refusing to report a pass when the check "
            "itself couldn't run -- this is a deploy-blocking failure, not a skip."
        )
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"`flyctl secrets list --app {app} --json` returned unparseable "
            f"output: {exc}. Refusing to report a pass on unparseable output."
        ) from exc
    return {row["Name"] for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="Fly app name (e.g. hie-api)")
    args = parser.parse_args()

    required = required_secrets()
    try:
        configured = _fetch_configured_secret_names(args.app)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    missing = list_missing_secrets(required, configured)
    if missing:
        print(
            f"ERROR: {len(missing)} required secret(s) not set on Fly app {args.app!r}:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - {name}: {required[name]}", file=sys.stderr)
        print(
            "\nSet each with `flyctl secrets set NAME=... --app "
            f"{args.app}` before deploying -- see D146/D150 in "
            "docs/DEFECT-REGISTER.md for why this check exists.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: all {len(required)} required secret(s) present on Fly app {args.app!r}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
