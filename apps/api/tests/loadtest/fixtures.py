"""Real book+chapter fixture provisioning for the Story 5-1 load-testing harness.

Phase B (`generate_chapter_lesson`, `POST /books/{book_id}/chapters/{chapter_id}
/lessons`) needs at least one REAL, `ready` book with at least one REAL
detected chapter to generate lessons against -- there is no way to call that
endpoint without a real `chapter_id` resolved from a real ingested book.
`ensure_book_chapter_fixture` provides exactly that, live-first:

  1. Check (service-role, live, bounded) whether `uploader` already owns a
     `ready` book with at least one detected chapter. If this harness has
     already been run once against this Supabase project, re-uploading the
     SAME PDF again on every subsequent run would waste real ingestion time
     (store -> extract -> structure_detect -> chunk -> embed) for no benefit
     -- Phase B's own load scenario wants a stable, already-known-good
     `(book_id, chapter_id)` pair it can hit repeatedly across many runs.
  2. Only if no such book+chapter exists yet: upload the real
     `tests/fixtures/eval_pdfs/short_10page.pdf` fixture as `uploader` (a real
     multipart HTTP POST through the real ingestion pipeline), poll the real
     book-status endpoint until it reaches `ready` (or fails/times out), then
     read its real detected chapters via the real chapters endpoint and
     return the first one.

Both paths return a chapter genuinely produced by the real chapter-detection
pipeline against a real PDF -- never a fabricated book_id/chapter_id, and
never a shortcut through `run_pipeline()` in-process (Story 5-1 AC-1 forbids
that shortcut for the load scenarios themselves; it would be equally wrong
for this fixture setup to take it, since a fixture built by a bypassed path
would not prove the real endpoint works).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from tests.loadtest.models import TestUser
from tests.loadtest.provisioning import _admin_headers, _require_env

# apps/api/tests/loadtest/fixtures.py -> parent.parent == apps/api/tests
_FIXTURE_PDF = (
    Path(__file__).resolve().parent.parent / "fixtures" / "eval_pdfs" / "short_10page.pdf"
)

_UPLOAD_PATH = "/api/content/lessons"
_REQUEST_TIMEOUT_S = 120.0

# Book ingestion (Phase A) is fast by design -- Story 1-10 measured <= 15s for
# a 1,000-page book, and this fixture PDF is only 10 pages -- so a 2s poll
# interval / 60s ceiling is generous, not tight, for a real end-to-end
# ingestion run.
_POLL_INTERVAL_S = 2.0
_POLL_TIMEOUT_S = 60.0


async def _find_existing_ready_book(uploader: TestUser) -> str | None:
    """Live, service-role, bounded check: does `uploader` already own a
    `ready` book? Returns its `book_id`, or None if not."""
    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = _admin_headers(service_role_key)

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        # BOUNDED: `limit=1` -- this only needs to know whether AT LEAST ONE
        # ready book exists for this one user, never every book they own.
        resp = await client.get(
            f"{supabase_url}/rest/v1/books",
            headers=headers,
            params={
                "select": "book_id,status",
                "user_id": f"eq.{uploader.user_id}",
                "status": "eq.ready",
                "limit": "1",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"live book lookup failed for {uploader.email}: {resp.status_code} {resp.text[:300]}"
        )
    rows: list[dict[str, str]] = resp.json()
    if not rows:
        return None
    return str(rows[0]["book_id"])


async def _find_first_chapter_id(book_id: str) -> str | None:
    """Live, service-role, bounded check: the first (lowest `chapter_index`)
    detected chapter for `book_id`, or None if the book has none yet."""
    supabase_url = _require_env("SUPABASE_URL").rstrip("/")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = _admin_headers(service_role_key)

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        # BOUNDED: `limit=1` -- only the first chapter is needed here; a
        # scenario that needs MULTIPLE distinct chapters (e.g. a Gate-7
        # oversubscription probe) reads the full list itself via the real
        # `GET /books/{book_id}/chapters` HTTP endpoint, not this helper.
        resp = await client.get(
            f"{supabase_url}/rest/v1/chapters",
            headers=headers,
            params={
                "select": "chapter_id",
                "book_id": f"eq.{book_id}",
                "order": "chapter_index.asc",
                "limit": "1",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"live chapter lookup failed for book {book_id}: {resp.status_code} {resp.text[:300]}"
        )
    rows: list[dict[str, str]] = resp.json()
    if not rows:
        return None
    return str(rows[0]["chapter_id"])


async def _upload_fixture_book(base_url: str, uploader: TestUser) -> str:
    """Real multipart POST of the real `short_10page.pdf` fixture as
    `uploader`. Returns the new `book_id`. Raises on any non-202 response --
    a failed upload must never be silently treated as "no fixture available
    yet"."""
    pdf_bytes = _FIXTURE_PDF.read_bytes()
    files = {"file": ("short_10page.pdf", pdf_bytes, "application/pdf")}
    headers = {"Authorization": f"Bearer {uploader.access_token}"}

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}{_UPLOAD_PATH}",
            files=files,
            headers=headers,
        )
    if resp.status_code != 202:
        raise RuntimeError(
            f"fixture upload failed for {uploader.email}: {resp.status_code} {resp.text[:300]}"
        )
    body = resp.json()
    book_id = body.get("book_id")
    if not book_id:
        raise RuntimeError(f"fixture upload response carried no book_id: {resp.text[:300]}")
    return str(book_id)


async def _poll_until_ready(base_url: str, uploader: TestUser, book_id: str) -> None:
    """Poll `GET /books/{book_id}` every `_POLL_INTERVAL_S`s until `status ==
    'ready'`. Raises on `status == 'failed'` (a real ingestion failure must
    surface, never be retried into a false timeout) and on exceeding
    `_POLL_TIMEOUT_S` (an explicit timeout -- never an infinite poll)."""
    headers = {"Authorization": f"Bearer {uploader.access_token}"}
    deadline = time.monotonic() + _POLL_TIMEOUT_S

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        while True:
            resp = await client.get(
                f"{base_url.rstrip('/')}/api/content/books/{book_id}",
                headers=headers,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"poll of book {book_id} failed: {resp.status_code} {resp.text[:300]}"
                )
            body = resp.json()
            status = body.get("status")
            if status == "ready":
                return
            if status == "failed":
                raise RuntimeError(f"fixture book {book_id} ingestion FAILED: {body}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"fixture book {book_id} did not reach 'ready' within "
                    f"{_POLL_TIMEOUT_S}s (last observed status: {status!r})"
                )
            await asyncio.sleep(_POLL_INTERVAL_S)


async def _first_chapter_via_api(base_url: str, uploader: TestUser, book_id: str) -> str:
    """Real `GET /books/{book_id}/chapters` as `uploader`; returns the first
    (lowest `chapter_index` -- the endpoint itself orders by `chapter_index`)
    chapter's id. Raises if the ready book somehow has zero detected
    chapters -- that would itself be a real defect worth surfacing loudly,
    never papered over as "just retry the upload"."""
    headers = {"Authorization": f"Bearer {uploader.access_token}"}
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/api/content/books/{book_id}/chapters",
            headers=headers,
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"chapter list failed for book {book_id}: {resp.status_code} {resp.text[:300]}"
        )
    chapters: list[dict[str, object]] = resp.json()
    if not chapters:
        raise RuntimeError(
            f"fixture book {book_id} reached 'ready' with zero detected chapters -- "
            "cannot provide a Phase B fixture chapter."
        )
    chapter_id = chapters[0].get("chapter_id")
    if not chapter_id:
        raise RuntimeError(
            f"chapter list response for book {book_id} had no chapter_id: {chapters[0]}"
        )
    return str(chapter_id)


async def ensure_book_chapter_fixture(base_url: str, uploader: TestUser) -> tuple[str, str]:
    """Return `(book_id, chapter_id)` of a REAL, `ready` book with at least
    one real detected chapter, owned by `uploader`.

    Checks live (service-role) first for an already-`ready` book with an
    already-detected chapter and reuses it if found; only uploads the real
    `short_10page.pdf` fixture and waits for real ingestion when nothing
    reusable exists yet. See the module docstring for the full rationale.
    """
    existing_book_id = await _find_existing_ready_book(uploader)
    if existing_book_id is not None:
        existing_chapter_id = await _find_first_chapter_id(existing_book_id)
        if existing_chapter_id is not None:
            return existing_book_id, existing_chapter_id
        # A 'ready' book with zero chapters would be unusual (chapter
        # detection runs inside the same ingestion job that sets status to
        # 'ready') but is handled defensively rather than assumed impossible
        # -- fall through to provisioning a fresh fixture book below.

    book_id = await _upload_fixture_book(base_url, uploader)
    await _poll_until_ready(base_url, uploader, book_id)
    chapter_id = await _first_chapter_via_api(base_url, uploader, book_id)
    return book_id, chapter_id
