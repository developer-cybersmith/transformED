"""Guards that `.env.example` agrees with what the code actually does (D31, D48, D62).

Story 3-35's whole premise is that a documented/templated config value silently
diverging from the code default it's supposed to describe is a real, recurring defect
class in this repo -- D62 (Langfuse host) and D31 (API URL prefix) are two independent
instances of exactly the same shape, and D48 is the adjacent failure mode: a config
value that LOOKS like a real control but has zero code enforcing it. RED phase: both
tests below must fail against the current `.env.example` / `config.py` -- if they pass
before the fix lands, they are not testing the real defect.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
APP_DIR = REPO_ROOT / "apps" / "api" / "app"
CONFIG_PY = APP_DIR / "config.py"

# Keys in `.env.example` that deliberately do NOT match their Settings field's code
# default, with the reason each is intentional documentation rather than drift. AC 6
# asks for exactly this: whitelist documented exceptions instead of comparing blindly.
_DOCUMENTED_EXCEPTIONS = {
    "REDIS_URL": (
        "shows a real Railway-format URL (CLAUDE.md locks Railway Redis for prod) "
        "rather than the redis://localhost:6379/0 dev default -- intentional, not drift"
    ),
}


def _parse_env_example() -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw_value = stripped.partition("=")
        key = key.strip()
        # Strip a trailing inline comment: "KEY=value    # comment"
        value = re.split(r"\s+#", raw_value, maxsplit=1)[0].strip()
        pairs[key] = value
    return pairs


def _references_identifier(source: str, identifier: str) -> bool:
    """True if `identifier` is a real `Name`/`Attribute` reference in `source`'s AST --
    not merely present inside a comment, docstring, or unrelated string literal.

    A bare `identifier in source` substring check (the original version of this guard)
    would count a stray comment or docstring mention as "a real reader," which is
    exactly the false-green D48's shape needs this guard to refuse. Comments are never
    part of the AST at all, and a docstring is an `ast.Constant` (a string value), not
    a `Name`/`Attribute` node -- so neither can satisfy this check by text alone.
    (Review finding, confirmed independently by two reviewers on Story 3-35's own
    adversarial review round.)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == identifier:
            return True
        if isinstance(node, ast.Attribute) and node.attr == identifier:
            return True
    return False


@pytest.mark.unit
def test_env_example_matches_settings_defaults_or_is_a_documented_exception() -> None:
    """D62's general-purpose guard.

    Every `.env.example` key that maps to a Settings field with a real (non-required,
    non-None) default must show that default's value, unless explicitly whitelisted in
    `_DOCUMENTED_EXCEPTIONS` above. This is the test that would have caught D62 before
    it shipped: LANGFUSE_HOST templated as http://localhost:3010 (self-hosted) while
    `config.py`'s real, live default is https://cloud.langfuse.com (Cloud) -- exactly
    the kind of silent divergence between documentation and the code path that actually
    runs which D31 shows nobody catches by reading alone.
    """
    env_pairs = _parse_env_example()
    mismatches: list[str] = []

    for key, env_value in env_pairs.items():
        if key in _DOCUMENTED_EXCEPTIONS:
            continue
        field_name = key.lower()
        field = Settings.model_fields.get(field_name)
        if field is None:
            continue  # not a backend Settings field (e.g. frontend NEXT_PUBLIC_* vars)
        if field.is_required():
            continue  # a real secret -- .env.example is expected to leave it blank/placeholder
        if field.default_factory is not None:
            # e.g. admin_emails/approved_emails (default_factory=list): `.default` is
            # PydanticUndefined, not a comparable scalar. Neither key is in
            # .env.example today, but a future addition must not silently compare
            # against the literal string "PydanticUndefined" (review finding,
            # confirmed independently by two reviewers on Story 3-35's own review).
            continue
        default = field.default
        if default is None:
            continue  # optional field with no meaningful default to compare
        if isinstance(default, bool):
            matches = env_value.strip().lower() == str(default).lower()
        elif isinstance(default, (int, float)):
            try:
                matches = float(env_value) == float(default)
            except ValueError:
                matches = False
        elif isinstance(default, list):
            continue  # list-typed fields (cors_origins) need JSON-aware comparison; not in scope
        else:
            matches = env_value.strip() == str(default).strip()
        if not matches:
            mismatches.append(
                f"{key}={env_value!r} in .env.example, but Settings.{field_name} "
                f"defaults to {default!r}"
            )

    assert not mismatches, (
        "`.env.example` disagrees with the real Settings default for these keys "
        "(fix the template, or add a `_DOCUMENTED_EXCEPTIONS` entry with a reason if "
        "the divergence is intentional):\n  " + "\n  ".join(mismatches)
    )


@pytest.mark.unit
def test_references_identifier_ignores_comments_and_docstrings() -> None:
    """Mutation-proof for `_references_identifier`: a comment or docstring mention must
    NOT count as a real reference, or the dead-config guard below would be satisfied by
    exactly the kind of stray mention it exists to refuse."""
    comment_only = "# uses max_daily_spend_per_user_usd for pricing, see config.py\nx = 1\n"
    docstring_only = '"""Docs mention max_daily_spend_per_user_usd here."""\nx = 1\n'
    real_attribute_access = "value = settings.max_daily_spend_per_user_usd\n"
    real_name_reference = "max_daily_spend_per_user_usd = 10.0\n"

    assert _references_identifier(comment_only, "max_daily_spend_per_user_usd") is False
    assert _references_identifier(docstring_only, "max_daily_spend_per_user_usd") is False
    assert _references_identifier(real_attribute_access, "max_daily_spend_per_user_usd") is True
    assert _references_identifier(real_name_reference, "max_daily_spend_per_user_usd") is True


@pytest.mark.unit
def test_max_daily_spend_per_user_usd_has_a_real_reader_or_does_not_exist() -> None:
    """D48's dead-config guard.

    `max_daily_spend_per_user_usd` must either be enforced by a reader somewhere
    outside `config.py`, or not exist as a Settings field at all. It must never sit in
    `config.py` looking like a real spend control while zero code paths read it -- the
    exact shape D48 found, and the same shape as D18/D29 (an artefact that exists,
    enforcement that was never built). Passing vacuously because the field was deleted
    is the intended GREEN state after this story's fix; passing because a reader
    exists would mean the story took option (a) instead -- either is fine, silence is not.
    """
    if "max_daily_spend_per_user_usd" not in Settings.model_fields:
        return  # deleted -- D48 resolved by removal, nothing left to guard

    readers = [
        str(py_file.relative_to(REPO_ROOT))
        for py_file in APP_DIR.rglob("*.py")
        if py_file != CONFIG_PY
        and _references_identifier(
            py_file.read_text(encoding="utf-8"), "max_daily_spend_per_user_usd"
        )
    ]

    assert readers, (
        "max_daily_spend_per_user_usd is defined in config.py with zero readers "
        "anywhere else in apps/api/app -- this is D48: dead config that reads like a "
        "real spend control. Either implement enforcement (a reader must appear "
        "outside config.py) or delete the field entirely."
    )
