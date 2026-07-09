"""
AC-7 (Story 2-0) — bucket provisioning as code.

Static manifest check (no Supabase credentials required): every storage
bucket referenced in apps/api/app source — by string literal OR by a simple
module-level constant — must be in the provisioned set, and every provisioned
bucket must appear in the 20260710000000_storage_buckets.sql migration.
A bucket referenced in code but absent from the migration would fail the
deploy-time lifespan assertion in app.main — this test catches it at
unit-test time instead.
"""

from __future__ import annotations

import re
from pathlib import Path

_API_APP_DIR = Path(__file__).resolve().parents[2] / "app"
_MAIN_PY = _API_APP_DIR / "main.py"
_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "supabase"
    / "migrations"
    / "20260710000000_storage_buckets.sql"
)

# Must mirror both the migration and the lifespan assertion in app.main
# (test_lifespan_assertion_matches_manifest enforces the latter).
_PROVISIONED = {"source-pdfs", "lesson-images", "lesson-audio", "avatar-clips"}

# Storage bucket access by string literal: supabase.storage.from_("...").
# (PostgREST table access `.from_("table")` without the .storage prefix is
# deliberately excluded.)
_BUCKET_LITERAL = re.compile(r"\.storage\.from_\(\s*[\"']([^\"']+)[\"']")

# Storage bucket access via a module-level constant:
#   _AVATAR_BUCKET = "avatar-clips"  ...  .storage.from_(_AVATAR_BUCKET)
_BUCKET_IDENTIFIER = re.compile(r"\.storage\.from_\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
_CONSTANT_ASSIGNMENT = r"^\s*{name}\s*(?::\s*[^=]+)?=\s*[\"']([^\"']+)[\"']"


def _referenced_buckets() -> set[str]:
    found: set[str] = set()
    for py_file in _API_APP_DIR.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        found |= set(_BUCKET_LITERAL.findall(source))
        # Resolve simple same-file module-level constants (e.g. _AVATAR_BUCKET).
        for identifier in _BUCKET_IDENTIFIER.findall(source):
            match = re.search(
                _CONSTANT_ASSIGNMENT.format(name=re.escape(identifier)),
                source,
                re.MULTILINE,
            )
            if match:
                found.add(match.group(1))
    return found


def test_every_referenced_bucket_is_provisioned() -> None:
    referenced = _referenced_buckets()
    assert referenced, "expected at least one .storage.from_(...) reference in app/"
    unprovisioned = referenced - _PROVISIONED
    assert not unprovisioned, (
        f"buckets referenced in code but not provisioned: {unprovisioned} — "
        "add them to supabase/migrations/20260710000000_storage_buckets.sql, "
        "the lifespan assertion in app/main.py, and _PROVISIONED here"
    )


def test_constant_based_bucket_access_is_resolved() -> None:
    """Guard the scanner itself: heygen.py's _AVATAR_BUCKET-style access must
    be visible to the manifest — a literal-only regex missed it once already."""
    assert "avatar-clips" in _referenced_buckets()


def test_migration_provisions_every_bucket() -> None:
    migration_text = _MIGRATION.read_text(encoding="utf-8")
    for bucket in _PROVISIONED | _referenced_buckets():
        assert bucket in migration_text, (
            f"bucket '{bucket}' missing from {_MIGRATION.name}"
        )


def test_lifespan_assertion_matches_manifest() -> None:
    """app.main's required_buckets set must stay in lockstep with this manifest."""
    match = re.search(r"required_buckets\s*=\s*\{([^}]*)\}", _MAIN_PY.read_text(encoding="utf-8"))
    assert match, "required_buckets set not found in app/main.py lifespan"
    lifespan_buckets = set(re.findall(r"[\"']([^\"']+)[\"']", match.group(1)))
    assert lifespan_buckets == _PROVISIONED


def test_migration_is_idempotent() -> None:
    """Re-running against manually created buckets must not fail the deploy."""
    migration_text = _MIGRATION.read_text(encoding="utf-8").lower()
    assert "on conflict (id) do nothing" in migration_text
