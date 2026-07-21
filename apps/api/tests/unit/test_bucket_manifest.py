"""
AC-7 (Story 2-0 + review decision D1) — bucket provisioning as code.

Two layers:

1. Static manifest check (no Supabase credentials required): every storage
   bucket referenced in apps/api/app source — by string literal OR by a simple
   module-level constant — must be in the provisioned set
   (app.core.storage.REQUIRED_BUCKETS, the single source of truth), and every
   provisioned bucket must appear in the 20260710000000_storage_buckets.sql
   migration as PRIVATE. Identifiers the scanner cannot statically resolve
   fail loudly instead of being silently skipped.

2. Behavioral check of app.core.storage.assert_required_buckets — the helper
   both app.main's lifespan and app.workers.main's startup call — with a
   mocked list_buckets: missing bucket, public bucket, and malformed entries
   must each raise a clear RuntimeError; a complete all-private set passes.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.storage import REQUIRED_BUCKETS, assert_required_buckets

_API_DIR = Path(__file__).resolve().parents[2]
_API_APP_DIR = _API_DIR / "app"
_MAIN_PY = _API_APP_DIR / "main.py"
_WORKER_MAIN_PY = _API_APP_DIR / "workers" / "main.py"
_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "supabase"
    / "migrations"
    / "20260710000000_storage_buckets.sql"
)

# The provisioned set IS the helper's constant — app.core.storage is the
# single source of truth; the migration-text crosscheck below keeps the SQL
# in lockstep with it.
_PROVISIONED = set(REQUIRED_BUCKETS)

# Dynamic references the scanner can NEVER statically resolve, reviewed and
# accepted manually. Key: "<path relative to app/>:<identifier>". Each entry
# must document why it is safe. A stale entry (reference removed) fails the
# scanner test so this list cannot rot.
_MANUAL_DYNAMIC_REFERENCES: frozenset[str] = frozenset(
    {
        # get_signed_url's `bucket` is a request query param constrained to the
        # module's _ALLOWED_BUCKETS allowlist before any storage call; the
        # .storage.from_(bucket) text is currently only a TODO docstring and the
        # endpoint returns 501. Runtime values are covered by the allowlist check.
        "modules/media/router.py:bucket",
    }
)

# Storage bucket access by string literal: supabase.storage.from_("...").
# (PostgREST table access `.from_("table")` without the .storage prefix is
# deliberately excluded.)
_BUCKET_LITERAL = re.compile(r"\.storage\.from_\(\s*[\"']([^\"']+)[\"']")

# Storage bucket access via a module-level constant:
#   _AVATAR_BUCKET = "avatar-clips"  ...  .storage.from_(_AVATAR_BUCKET)
_BUCKET_IDENTIFIER = re.compile(r"\.storage\.from_\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
_CONSTANT_ASSIGNMENT = r"^\s*{name}\s*(?::\s*[^=]+)?=\s*[\"']([^\"']+)[\"']"


# ── Static manifest scanner ──────────────────────────────────────────────────


def _scan_bucket_references() -> tuple[set[str], set[str]]:
    """Return (resolved bucket names, unresolvable identifier references)."""
    found: set[str] = set()
    unresolved: set[str] = set()
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
            else:
                rel = py_file.relative_to(_API_APP_DIR).as_posix()
                unresolved.add(f"{rel}:{identifier}")
    return found, unresolved


def _referenced_buckets() -> set[str]:
    return _scan_bucket_references()[0]


def test_every_referenced_bucket_is_provisioned() -> None:
    referenced = _referenced_buckets()
    assert referenced, "expected at least one .storage.from_(...) reference in app/"
    unprovisioned = referenced - _PROVISIONED
    assert not unprovisioned, (
        f"buckets referenced in code but not provisioned: {unprovisioned} — "
        "add them to supabase/migrations/20260710000000_storage_buckets.sql "
        "and to REQUIRED_BUCKETS in app/core/storage.py"
    )


def test_constant_based_bucket_access_is_resolved() -> None:
    """Guard the scanner itself: heygen.py's _AVATAR_BUCKET-style access must
    be visible to the manifest — a literal-only regex missed it once already."""
    assert "avatar-clips" in _referenced_buckets()


def test_no_unresolvable_bucket_identifiers() -> None:
    """Fail loudly on identifiers the scanner cannot resolve to a constant —
    a silently-skipped reference would evade the manifest entirely."""
    _, unresolved = _scan_bucket_references()
    unaccounted = unresolved - _MANUAL_DYNAMIC_REFERENCES
    assert not unaccounted, (
        f"bucket name not statically resolvable — add to manifest manually "
        f"(_MANUAL_DYNAMIC_REFERENCES, with a safety justification) or hoist "
        f"to a same-file module-level string constant: {sorted(unaccounted)}"
    )
    stale = _MANUAL_DYNAMIC_REFERENCES - unresolved
    assert not stale, (
        f"stale _MANUAL_DYNAMIC_REFERENCES entries (reference no longer in "
        f"code — remove them): {sorted(stale)}"
    )


def test_migration_provisions_every_bucket() -> None:
    migration_text = _MIGRATION.read_text(encoding="utf-8")
    for bucket in _PROVISIONED | _referenced_buckets():
        assert bucket in migration_text, f"bucket '{bucket}' missing from {_MIGRATION.name}"


def test_migration_provisions_all_buckets_private() -> None:
    """D1: lesson content is paid — every bucket row must be public=false."""
    migration_text = _MIGRATION.read_text(encoding="utf-8").lower()
    rows = re.findall(r"\(\s*'([^']+)'\s*,\s*'[^']+'\s*,\s*(\w+)\s*\)", migration_text)
    assert {name for name, _ in rows} == _PROVISIONED
    public_rows = [name for name, flag in rows if flag != "false"]
    assert not public_rows, (
        f"buckets provisioned public in {_MIGRATION.name}: {public_rows} — "
        "all buckets are private per review decision D1 (signed URLs only)"
    )


def test_migration_is_idempotent_and_reconciles_visibility() -> None:
    """Re-running against manually created buckets must not fail the deploy,
    and must reconcile a manually-created bucket's `public` flag (D1)."""
    migration_text = _MIGRATION.read_text(encoding="utf-8").lower()
    assert "on conflict (id) do update set public = excluded.public" in migration_text
    assert "do nothing" not in migration_text, (
        "DO NOTHING never reconciles the public flag of pre-existing buckets"
    )


def test_startup_paths_call_shared_assertion() -> None:
    """Both the FastAPI lifespan and the ARQ worker startup must run the
    shared helper — a worker deployed against a missing/public bucket must
    fail at startup, not first upload."""
    for path in (_MAIN_PY, _WORKER_MAIN_PY):
        source = path.read_text(encoding="utf-8")
        assert "from app.core.storage import assert_required_buckets" in source, (
            f"{path.name} must import assert_required_buckets from app.core.storage"
        )
        assert re.search(r"to_thread\(\s*assert_required_buckets\s*,", source), (
            f"{path.name} must call assert_required_buckets at startup"
        )


# ── Behavioral tests of assert_required_buckets ──────────────────────────────


def _client(buckets: list) -> SimpleNamespace:  # type: ignore[type-arg]
    return SimpleNamespace(storage=SimpleNamespace(list_buckets=lambda: buckets))


def _private(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, public=False)


def test_assert_passes_when_all_present_and_private() -> None:
    # Mix attribute-style (supabase SyncBucket) and dict-style entries.
    buckets = [_private(n) for n in sorted(REQUIRED_BUCKETS)[:2]]
    buckets += [{"name": n, "public": False} for n in sorted(REQUIRED_BUCKETS)[2:]]
    buckets.append({"name": "unrelated-extra", "public": True})  # extras ignored
    assert_required_buckets(_client(buckets))  # must not raise


def test_assert_raises_naming_missing_bucket() -> None:
    buckets = [_private(n) for n in sorted(REQUIRED_BUCKETS) if n != "lesson-audio"]
    with pytest.raises(RuntimeError, match=r"Missing storage buckets.*lesson-audio"):
        assert_required_buckets(_client(buckets))


def test_assert_raises_naming_public_bucket() -> None:
    buckets = [
        SimpleNamespace(name=n, public=(n == "lesson-images")) for n in sorted(REQUIRED_BUCKETS)
    ]
    with pytest.raises(RuntimeError, match=r"must be private.*lesson-images"):
        assert_required_buckets(_client(buckets))


def test_assert_raises_clear_error_on_malformed_entry() -> None:
    buckets = [_private(n) for n in sorted(REQUIRED_BUCKETS)]
    buckets.append({"id": "no-name-key"})  # no 'name' attr or key
    with pytest.raises(RuntimeError, match=r"Malformed storage bucket entry"):
        assert_required_buckets(_client(buckets))


def test_assert_raises_when_visibility_unknown() -> None:
    """An entry with no public flag cannot be verified private — fail."""
    buckets = [_private(n) for n in sorted(REQUIRED_BUCKETS) if n != "source-pdfs"]
    buckets.append({"name": "source-pdfs"})  # visibility missing
    with pytest.raises(RuntimeError, match=r"must be private.*source-pdfs"):
        assert_required_buckets(_client(buckets))


def test_assert_wraps_list_buckets_failure() -> None:
    def _boom() -> list:  # type: ignore[type-arg]
        raise ConnectionError("storage API down")

    client = SimpleNamespace(storage=SimpleNamespace(list_buckets=_boom))
    with pytest.raises(RuntimeError, match=r"Could not list Supabase storage buckets"):
        assert_required_buckets(client)
