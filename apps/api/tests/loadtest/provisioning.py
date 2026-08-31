"""Real Supabase user provisioning for the Story 5-1 load-testing harness.

Every function here talks to the REAL, live Supabase project named by
`SUPABASE_URL`/`SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` in
`apps/api/.env` -- there is no mock, no local Postgres, no stand-in. This is
deliberate: Story 5-1 exists to measure real HTTP behavior against a real
running API + real Supabase project, and a self-minted JWT would not even
authenticate against it (see the module docstring on `mint_real_access_token`
below for why).

Config is read via `dotenv_values()` directly rather than `app.config.Settings`
-- this module is a standalone test/ops script, not application code, and
should be runnable in total isolation from the FastAPI app's own settings
plumbing (matching the convention already established for this project's
other live-Supabase test scripts).

Two DIFFERENT user-sourcing strategies are used, on purpose, for the two load
phases (see `docs/stories/5-1-load-test-50-concurrent.md`):

  * Phase A (`get_approved_test_users`) -- `upload_lesson` requires
    `ApprovedUser` (a static `APPROVED_EMAILS` allowlist gate,
    `app/dependencies.py:require_approved_user`), and today only 3 real
    accounts are on that allowlist. Story 5-1 AC-2 does not require distinct
    users the way AC-3 does, so Phase A reuses those 3 existing approved
    accounts (cycled round-robin by the caller) rather than mutating a
    production config value (`APPROVED_EMAILS`) just to run a load test.

  * Phase B (`provision_generate_test_users`) -- `generate_chapter_lesson`
    requires only `CurrentUser` (any authenticated user, no allowlist), and
    AC-3 explicitly requires >= 17 DISTINCT users (so
    `max_concurrent_generations_per_user = 3` cannot itself become the
    bottleneck standing in for "50 concurrent"). Freshly-created disposable
    users need no config change at all, so Phase B mints brand-new,
    self-cleaning accounts instead of touching the allowlist.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from dotenv import dotenv_values

from tests.loadtest.models import TestUser

logger = logging.getLogger(__name__)

# apps/api/tests/loadtest/provisioning.py -> parents[2] == apps/api
_API_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _API_ROOT / ".env"

# Generous but bounded -- Admin API calls (generate_link, create user, delete
# user) are simple single-row operations; 30s is well above their normal
# latency and still fails loudly instead of hanging the harness forever on a
# genuinely wedged network call.
_ADMIN_TIMEOUT_S = 30.0

# Bounds concurrent Auth Admin API calls during provisioning -- confirmed
# live that firing 30+ users' worth of create-user/generate_link/verify
# calls fully unbounded trips Supabase's OWN rate limit
# (429 over_request_rate_limit), independent of anything in this app. Not
# benchmarked against Supabase's exact published ceiling (undocumented for
# this endpoint at the time this was found) -- a conservative starting
# point, same reasoning as image_generator_node's own
# _IMAGE_GENERATION_CONCURRENCY=3 for an undocumented provider limit.
_PROVISION_CONCURRENCY = 5

# Story 5-1 Task 2 email pattern for disposable Phase B users.
_LOADTEST_EMAIL_PREFIX = "loadtest-"
_LOADTEST_EMAIL_SUFFIX = "-deleteme@seed.test"

_APPROVED_EMAILS_ENV_VAR = "APPROVED_EMAILS"


# ── Config loading (dotenv_values, not pydantic Settings -- see module docstring) ──


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str | None]:
    """Load `apps/api/.env` once per process. Cached: every caller in this
    module re-reads the same small dict rather than re-parsing the file."""
    return dotenv_values(_ENV_PATH)


def _require_env(key: str) -> str:
    """Fetch `key` from `.env`, falling back to a real process env var of the
    same name (so `FOO=bar python -m ...` still works without a `.env` edit).
    Raises loudly -- a missing credential must never silently degrade into a
    request that fails somewhere else with a confusing 401."""
    value = _dotenv().get(key) or os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"{key} not found in {_ENV_PATH} or the process environment -- this "
            "harness needs real Supabase credentials to mint real sessions."
        )
    return value


def _admin_headers(service_role_key: str) -> dict[str, str]:
    """Headers required by every Supabase Admin API / service-role REST call:
    `apikey` (required by Supabase's edge gateway) AND `Authorization: Bearer`
    (required by GoTrue/PostgREST itself) -- both, not either."""
    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }


def _parse_email_allowlist(raw: str) -> list[str]:
    """Mirror `app.config.Settings._parse_email_allowlist`'s parsing rules
    (comma-separated, or a JSON array string) WITHOUT importing
    `app.config` -- this module deliberately has no dependency on the FastAPI
    app's settings plumbing. Kept in sync by inspection, not by import,
    because a standalone test script importing the app's Settings object
    would need the full app config (including provider API keys this harness
    never uses) just to read one string."""
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        return [str(email).strip().lower() for email in parsed if str(email).strip()]
    return [email.strip().lower() for email in stripped.split(",") if email.strip()]


# ── Real session minting ─────────────────────────────────────────────────────


async def mint_real_access_token(email: str) -> str:
    """Mint a REAL, live Supabase access token for `email` via the
    service-role Admin API -- never a self-minted token.

    This project has migrated to Supabase's asymmetric JWT Signing Keys
    (confirmed live via `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
    returning an ES256 key): a token hand-signed with `SUPABASE_JWT_SECRET`
    using HS256 is cryptographically rejected by the live PostgREST/GoTrue
    API even with a correct `sub` claim, because Supabase alone holds the
    ES256 private key. The only way to get a real, verifiable session for an
    existing user without their password is:

      1. POST /auth/v1/admin/generate_link (type=magiclink, service-role
         auth) -- returns an `action_link` a real magic-link email would have
         pointed at, without ever sending an email.
      2. GET that `action_link` with redirects disabled -- Supabase's auth
         server issues a real session and responds with an HTTP 303 whose
         `Location` header carries `#access_token=...&refresh_token=...` in
         the URL FRAGMENT (never the query string -- fragments are the
         standard OAuth/implicit-flow convention for not leaking tokens into
         server access logs).
      3. Parse that fragment for `access_token`.

    Raises `RuntimeError` (never returns an empty/placeholder token) on any
    unexpected shape at any step -- a load-test harness silently proceeding
    with a bad token would misreport every subsequent 401 as an API defect
    instead of a harness bug.
    """
    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = {**_admin_headers(service_role_key), "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=_ADMIN_TIMEOUT_S) as client:
        link_resp = await client.post(
            f"{supabase_url}/auth/v1/admin/generate_link",
            headers=headers,
            json={"type": "magiclink", "email": email},
        )
        if link_resp.status_code >= 400:
            raise RuntimeError(
                f"generate_link failed for {email}: {link_resp.status_code} "
                f"{link_resp.text[:300]}"
            )
        action_link = link_resp.json().get("action_link")
        if not action_link:
            raise RuntimeError(
                f"generate_link response for {email} carried no action_link: "
                f"{link_resp.text[:300]}"
            )

        redirect_resp = await client.get(action_link, follow_redirects=False)
        if redirect_resp.status_code != 303:
            raise RuntimeError(
                f"expected a 303 redirect fetching the action_link for {email}, got "
                f"{redirect_resp.status_code}: {redirect_resp.text[:300]}"
            )
        # httpx.Headers.get()'s stub resolves to Any when called with only one
        # argument -- annotated explicitly so the real access_token this
        # function returns is provably `str`, not silently `Any` all the way
        # out (mypy strict: no-any-return).
        location: str | None = redirect_resp.headers.get("location")
        if not location:
            raise RuntimeError(f"303 redirect for {email} carried no Location header")

    fragment = urlsplit(location).fragment
    params = parse_qs(fragment)
    access_tokens = params.get("access_token")
    if not access_tokens:
        raise RuntimeError(
            f"Location fragment for {email} had no access_token: {location[:300]}"
        )
    return access_tokens[0]


# ── Phase B: disposable users ────────────────────────────────────────────────


class _PartialUserCreationError(RuntimeError):
    """Raised when a real `auth.users` row WAS created for a disposable Phase
    B test account but a later step (token minting) failed before a `TestUser`
    could be returned.

    This carries `user_id`/`email` so the caller can still find and delete
    the orphaned real row -- without this, a token-mint failure would create
    a real, permanent row in the live `auth.users` table that is never
    returned to any caller and therefore never passed to
    `cleanup_generate_test_users`, leaking a real account on every such
    failure."""

    def __init__(self, user_id: str, email: str, cause: BaseException) -> None:
        super().__init__(f"user {email} ({user_id}) created but token mint failed: {cause}")
        self.user_id = user_id
        self.email = email


async def _create_one_disposable_user(client: httpx.AsyncClient, index: int) -> TestUser:
    """Create ONE real, disposable `auth.users` row + mint its real session.

    `email_confirm: true` is required -- without it the created account sits
    unconfirmed and every authenticated request would 401 exactly like a real
    unverified signup, which is not what this harness is testing.

    Raises `_PartialUserCreationError` (carrying the real `user_id`/`email`,
    not a bare exception) if the user row is created but the subsequent token
    mint fails, so `provision_generate_test_users` can still clean up the
    orphaned real row rather than silently losing track of it.
    """
    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = {**_admin_headers(service_role_key), "Content-Type": "application/json"}

    email = f"{_LOADTEST_EMAIL_PREFIX}{index}{_LOADTEST_EMAIL_SUFFIX}"
    password = secrets.token_urlsafe(24)  # real random password; never reused, never logged

    create_resp = await client.post(
        f"{supabase_url}/auth/v1/admin/users",
        headers=headers,
        json={"email": email, "password": password, "email_confirm": True},
    )
    if create_resp.status_code >= 400:
        raise RuntimeError(
            f"admin create user failed for {email}: {create_resp.status_code} "
            f"{create_resp.text[:300]}"
        )
    body = create_resp.json()
    # GoTrue's admin-create-user response shape has varied across versions
    # between a bare user object and {"user": {...}} -- accept either rather
    # than assume one and fail confusingly on the other.
    user_id = body.get("id") or (body.get("user") or {}).get("id")
    if not user_id:
        raise RuntimeError(
            f"admin create user response for {email} carried no id: "
            f"{create_resp.text[:300]}"
        )

    try:
        access_token = await mint_real_access_token(email)
    except Exception as exc:
        # The real auth.users row above WAS created -- surface it as a
        # _PartialUserCreationError (not a bare exception) so the caller can
        # still delete it instead of orphaning a real account.
        raise _PartialUserCreationError(str(user_id), email, exc) from exc
    return TestUser(user_id=str(user_id), email=email, access_token=access_token)


async def provision_generate_test_users(n: int, *, offset: int = 0) -> list[TestUser]:
    """Create `n` REAL, disposable Supabase Auth users for Phase B (AC-3's
    >= 17 distinct users), each with a real minted session.

    `offset` shifts the `loadtest-{i}-deleteme@seed.test` index range so this
    can be called twice in the same run (e.g. Phase A's own disposable-account
    pool, separately from Phase B's) without colliding on the same email --
    every `loadtest-N` up to 49 is pre-approved in `apps/api/.env`'s
    `APPROVED_EMAILS`, so callers just need non-overlapping index ranges.

    WILL create real rows in the live `auth.users` table (and, via the
    project's `handle_new_auth_user` trigger, a matching real `public.users`
    row) the moment this is actually invoked -- not something this build step
    runs itself, per this task's instructions. Pair every real call with
    `cleanup_generate_test_users` once the load-test run is done.

Creations run concurrently but bounded by `_PROVISION_CONCURRENCY` (a
    `Semaphore`, one shared `httpx.AsyncClient` for connection reuse) --
    provisioning 17+ users sequentially would itself take long enough to be
    an annoying setup tax on every harness run, but firing ALL of them fully
    unbounded (as an earlier version of this function did) hits Supabase's
    OWN Auth Admin API rate limit once a full-scale run provisions 30+ users
    at once (each needing 2-3 real Admin API calls: create-user,
    generate_link, verify) -- confirmed live: a 32-user full run hit
    `429 over_request_rate_limit` from Supabase itself, not from this app.
    The partial-failure cleanup below already handled that gracefully (zero
    orphaned rows), but bounding concurrency here avoids provoking Supabase's
    limit in the first place rather than just recovering from it every time.

    If ANY of the concurrent creations fails, this does NOT return the
    partial list and leave the successfully-created real rows to leak: it
    collects every user that WAS actually created (both fully-usable
    `TestUser`s and rows whose token mint failed, via
    `_PartialUserCreationError`), best-effort deletes all of them via
    `cleanup_generate_test_users`, and only then raises -- so a partial
    provisioning failure never leaves permanent, untracked residue on the
    real Supabase project.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")

    limits = httpx.Limits(max_connections=n + 5, max_keepalive_connections=n)
    sem = asyncio.Semaphore(_PROVISION_CONCURRENCY)

    async with httpx.AsyncClient(timeout=_ADMIN_TIMEOUT_S, limits=limits) as client:

        async def _bounded_create(index: int) -> TestUser:
            async with sem:
                return await _create_one_disposable_user(client, index)

        results = await asyncio.gather(
            *(_bounded_create(offset + i) for i in range(n)),
            return_exceptions=True,
        )

    users: list[TestUser] = []
    created_but_unusable: list[TestUser] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result, TestUser):
            users.append(result)
        elif isinstance(result, _PartialUserCreationError):
            # A real row exists (user_id/email known) but has no usable
            # access_token -- track it ONLY for cleanup, never for use in a
            # load scenario.
            created_but_unusable.append(
                TestUser(user_id=result.user_id, email=result.email, access_token="")
            )
            errors.append(str(result))
        elif isinstance(result, BaseException):
            # No real row was created for this index (the create-user call
            # itself failed) -- nothing to clean up for this one.
            errors.append(f"{type(result).__name__}: {result}")

    if errors:
        to_clean = users + created_but_unusable
        if to_clean:
            try:
                await cleanup_generate_test_users(to_clean)
            except Exception as cleanup_exc:  # noqa: BLE001 -- best-effort, report and still raise
                errors.append(
                    f"cleanup of {len(to_clean)} partially-provisioned user(s) also "
                    f"failed: {cleanup_exc}"
                )
        raise RuntimeError(
            f"provision_generate_test_users: {len(errors)} of {n} creation(s) failed "
            f"({len(to_clean)} real row(s) created during this failed attempt were "
            f"best-effort cleaned up): {errors}"
        )

    return users


async def _delete_one_user(
    client: httpx.AsyncClient, headers: dict[str, str], base_url: str, user: TestUser
) -> str | None:
    """Delete one user; returns an error string on failure, None on success
    (including a 404 -- already gone counts as cleaned up, not a failure)."""
    resp = await client.delete(f"{base_url}/auth/v1/admin/users/{user.user_id}", headers=headers)
    if resp.status_code >= 400 and resp.status_code != 404:
        return f"{user.email} ({user.user_id}): {resp.status_code} {resp.text[:200]}"
    return None


async def cleanup_generate_test_users(users: list[TestUser]) -> None:
    """Delete every disposable user created by `provision_generate_test_users`.

    Attempts EVERY deletion even if some fail (never stops at the first
    error) -- a partial cleanup that silently gives up after user #3 would
    leak the remaining disposable accounts with no signal that it happened.
    Raises `RuntimeError` listing every failure AFTER all deletes have been
    attempted, so one bad row never blocks cleanup of the rest.
    """
    if not users:
        return

    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = _admin_headers(service_role_key)

    limits = httpx.Limits(max_connections=len(users) + 5, max_keepalive_connections=len(users))
    sem = asyncio.Semaphore(_PROVISION_CONCURRENCY)
    async with httpx.AsyncClient(timeout=_ADMIN_TIMEOUT_S, limits=limits) as client:

        async def _bounded_delete(user: TestUser) -> str | None:
            async with sem:
                return await _delete_one_user(client, headers, supabase_url, user)

        results = await asyncio.gather(*(_bounded_delete(user) for user in users))

    failures = [r for r in results if r is not None]
    if failures:
        for failure in failures:
            logger.warning("cleanup_generate_test_users: failed to delete %s", failure)
        raise RuntimeError(
            f"cleanup_generate_test_users: {len(failures)} of {len(users)} deletions "
            f"failed: {failures}"
        )


async def _delete_one_uploaded_book(
    client: httpx.AsyncClient, headers: dict[str, str], supabase_url: str, book: dict[str, str]
) -> str | None:
    """Best-effort delete of ONE real book created by Phase A's load
    scenario: the storage object first, then the `books` row (whose
    `ON DELETE CASCADE` to `chapters`/`chunks` -- confirmed in
    `20260611000000_initial_schema.sql` / `20260625000000_chunks_inline_embedding.sql`
    -- cleans those up too). Returns an error string on failure, None on
    success (including a 404 on either delete -- already gone counts as
    cleaned up)."""
    book_id = book["book_id"]
    storage_path = f"{book['user_id']}/{book_id}/{book['filename']}"

    storage_resp = await client.post(
        f"{supabase_url}/storage/v1/object/remove/source-pdfs",
        headers={**headers, "Content-Type": "application/json"},
        json={"prefixes": [storage_path]},
    )
    if storage_resp.status_code >= 400 and storage_resp.status_code != 404:
        return (
            f"book {book_id}: storage remove failed: {storage_resp.status_code} "
            f"{storage_resp.text[:200]}"
        )

    books_resp = await client.delete(
        f"{supabase_url}/rest/v1/books",
        headers=headers,
        params={"book_id": f"eq.{book_id}"},
    )
    if books_resp.status_code >= 400 and books_resp.status_code != 404:
        return (
            f"book {book_id}: books row delete failed: {books_resp.status_code} "
            f"{books_resp.text[:200]}"
        )
    return None


async def cleanup_uploaded_books(books: list[dict[str, str]]) -> None:
    """Delete every real `books` row (+ storage object) created by Phase A's
    load scenario (`phase_a_upload.run_phase_a`'s `extra["created_books"]`).

    Phase A deliberately reuses the 3 REAL `APPROVED_EMAILS` accounts rather
    than minting disposable ones (`get_approved_test_users`'s docstring --
    `upload_lesson` requires `ApprovedUser`), so unlike
    `cleanup_generate_test_users` this is NOT deleting a disposable account --
    it is deleting only the specific book/chapter/chunk rows and storage
    object THIS run created, on an account that continues to exist and be
    used for real. Without this, every full-scale run permanently leaves its
    real book uploads on those real accounts with no other cleanup path
    (there is no `DELETE /books/{book_id}` HTTP endpoint in the app to use
    instead -- see `router.py`, which only ever deletes a book row as its own
    internal compensating action, never via a caller-facing route).

    Attempts EVERY deletion even if some fail (never stops at the first
    error), matching `cleanup_generate_test_users`'s discipline. Raises
    `RuntimeError` listing every failure AFTER all deletes have been
    attempted.
    """
    if not books:
        return

    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = _admin_headers(service_role_key)

    limits = httpx.Limits(max_connections=len(books) + 5, max_keepalive_connections=len(books))
    async with httpx.AsyncClient(timeout=_ADMIN_TIMEOUT_S, limits=limits) as client:
        results = await asyncio.gather(
            *(_delete_one_uploaded_book(client, headers, supabase_url, book) for book in books)
        )

    failures = [r for r in results if r is not None]
    if failures:
        for failure in failures:
            logger.warning("cleanup_uploaded_books: failed to delete %s", failure)
        raise RuntimeError(
            f"cleanup_uploaded_books: {len(failures)} of {len(books)} deletions "
            f"failed: {failures}"
        )


# ── Phase A: reused approved users ───────────────────────────────────────────


async def get_approved_test_users() -> list[TestUser]:
    """Mint real sessions for the existing `APPROVED_EMAILS` accounts, for
    Phase A (`upload_lesson` requires `ApprovedUser`, so only these accounts
    can exercise that endpoint at all today).

    User ids are looked up LIVE from the real `public.users` table by email
    (never hardcoded) -- a project reset changes every UUID, and a hardcoded
    id would silently mint a token for the wrong account or fail outright
    once the project's data is reset.
    """
    raw = _require_env(_APPROVED_EMAILS_ENV_VAR)
    emails = _parse_email_allowlist(raw)
    if not emails:
        raise RuntimeError(
            f"{_APPROVED_EMAILS_ENV_VAR} in {_ENV_PATH} parsed to an empty list -- "
            "Phase A needs at least one real approved account to reuse."
        )

    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = _admin_headers(service_role_key)

    async with httpx.AsyncClient(timeout=_ADMIN_TIMEOUT_S) as client:
        # BOUNDED: `limit` is set to exactly `len(emails)` -- this query can
        # never return more rows than the (small, hand-maintained, currently
        # 3-entry) allowlist itself supplies, so it is bounded by the caller's
        # own input, not by the size of the `users` table.
        resp = await client.get(
            f"{supabase_url}/rest/v1/users",
            headers=headers,
            params={
                "select": "id,email",
                "email": f"in.({','.join(emails)})",
                "limit": str(len(emails)),
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"live lookup of approved users failed: {resp.status_code} {resp.text[:300]}"
        )

    rows: list[dict[str, str]] = resp.json()
    by_email = {str(row["email"]).strip().lower(): str(row["id"]) for row in rows}

    missing = [email for email in emails if email not in by_email]
    if missing:
        raise RuntimeError(
            f"approved email(s) not found in the live public.users table: {missing} -- "
            "these real accounts must already exist before Phase A can reuse them "
            "(this harness never creates or expands the approved allowlist)."
        )

    return list(
        await asyncio.gather(
            *(_build_approved_test_user(email, by_email[email]) for email in emails)
        )
    )


async def _build_approved_test_user(email: str, user_id: str) -> TestUser:
    access_token = await mint_real_access_token(email)
    return TestUser(user_id=user_id, email=email, access_token=access_token)
