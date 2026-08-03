"""Story 2-35 / D18: `POST /api/assessment/sessions` mints the session row.

Why this file exists
--------------------
**Nothing anywhere created a `sessions` row.** All 7 `table("sessions")`
references in `apps/api` were `.select(...)`; `apps/web` never inserted one
either; `player.machine.ts:142` invented `crypto.randomUUID()`. So
`service.py`'s ownership check correctly 404'd on an id that had never existed,
and **quiz and teach-back returned 404 for every student, always.**

Both suites were green the whole time: Dev 3 seeded the row in fixtures, Dev 2
mocked the POST. Nothing reconciled the two halves — `DEFECT-REGISTER.md` RC-1.

Ownership note
--------------
This lands in `app/modules/assessment/` — **Dev 3's module** — because that is
where the table's reads already live. Dev 1 implemented it under option B of
`docs/handoffs/dev3-handoff-2026-07-29.md` §1 (Dev 1 implements, Dev 3 reviews
before merge). A deliberate crossing of CLAUDE.md §5.4, not an oversight.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user
from app.modules.assessment.router import router

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
LESSON_ID = "33333333-3333-3333-3333-333333333333"
MINTED_SESSION_ID = "44444444-4444-4444-4444-444444444444"


async def _fake_user() -> dict:
    return {"sub": USER_ID, "email": "student@example.com"}


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_UNAUTH_APP = FastAPI()
_UNAUTH_APP.include_router(router, prefix="/api/assessment")
_unauth_client = TestClient(_UNAUTH_APP, raise_server_exceptions=False)


@pytest.fixture
def mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.to_thread with a synchronous shim (module convention)."""

    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


def _supabase(
    *,
    lesson_owner: str | None = USER_ID,
    insert_returns: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Supabase stub: a lessons ownership read, then a sessions insert.

    `lesson_owner=None` models a lesson that does not exist. AC-2 requires the
    same 404 for that and for a lesson owned by someone else.
    """
    sb = MagicMock()
    inserted: list[dict[str, Any]] = []

    lesson_row = None if lesson_owner is None else {"lesson_id": LESSON_ID, "user_id": lesson_owner}

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "lessons":
            (
                t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
            ) = lesson_row
        elif name == "sessions":

            def _insert(payload: dict[str, Any]) -> MagicMock:
                inserted.append(payload)
                ex = MagicMock()
                ex.execute.return_value.data = (
                    insert_returns
                    if insert_returns is not None
                    else [
                        {
                            "session_id": MINTED_SESSION_ID,
                            "user_id": USER_ID,
                            "lesson_id": LESSON_ID,
                            "started_at": "2026-07-29T12:00:00+00:00",
                        }
                    ]
                )
                return ex

            t.insert.side_effect = _insert
        return t

    sb.table.side_effect = _table
    sb.inserted = inserted  # exposed for AC-1's "never accepted from the client" assertion
    return sb


def _post(sb: MagicMock, body: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
    from unittest.mock import patch

    with patch("app.core.db.get_supabase", return_value=sb):
        return _client.post(
            "/api/assessment/sessions",
            json=body if body is not None else {"lesson_id": LESSON_ID},
        )


# ── AC-1: the endpoint mints a session and returns its id ────────────────────


@pytest.mark.unit
def test_creates_a_session_and_returns_the_database_generated_id(mock_to_thread: None) -> None:
    sb = _supabase()
    resp = _post(sb)

    assert resp.status_code == 201, resp.text
    assert resp.json()["session_id"] == MINTED_SESSION_ID


@pytest.mark.unit
def test_user_id_comes_from_the_jwt_and_is_never_accepted_from_the_client(
    mock_to_thread: None,
) -> None:
    """A client-supplied user_id must be ignored, not trusted.

    Without this, any authenticated student could mint a session belonging to
    another user and then read their quiz history through the session-scoped
    endpoints.
    """
    sb = _supabase()
    resp = _post(sb, {"lesson_id": LESSON_ID, "user_id": OTHER_USER_ID})

    assert resp.status_code == 201, resp.text
    assert len(sb.inserted) == 1
    assert sb.inserted[0]["user_id"] == USER_ID, (
        f"user_id must come from the verified JWT, got {sb.inserted[0]['user_id']}"
    )


@pytest.mark.unit
def test_session_id_and_started_at_are_not_sent_to_the_database(mock_to_thread: None) -> None:
    """Both are DB-generated (`DEFAULT gen_random_uuid()` / `DEFAULT now()`).

    Sending either would defeat the point: a client-chosen id reintroduces D18,
    and a client-chosen started_at makes session duration meaningless.
    """
    sb = _supabase()
    resp = _post(sb, {"lesson_id": LESSON_ID, "session_id": "client-chosen", "started_at": "1999"})

    assert resp.status_code == 201, resp.text
    payload = sb.inserted[0]
    assert "session_id" not in payload, "session_id must be database-generated"
    assert "started_at" not in payload, "started_at must be database-generated"


@pytest.mark.unit
def test_unauthenticated_request_is_rejected() -> None:
    """HTTPBearer(auto_error=True) returns 403 for a missing token; the JWT
    dependency itself raises 401 for an invalid one. Both are correct rejections —
    the established pattern in this suite asserts `in (401, 403)`.
    """
    resp = _unauth_client.post("/api/assessment/sessions", json={"lesson_id": LESSON_ID})
    assert resp.status_code in (401, 403), (
        f"Expected 401 or 403 for unauthenticated request, got {resp.status_code}"
    )


# ── AC-2: absence and non-ownership are indistinguishable ────────────────────


@pytest.mark.unit
def test_a_lesson_owned_by_someone_else_returns_404_not_403(mock_to_thread: None) -> None:
    """A distinct 403 would leak lesson existence to a non-owner.

    Matches the established pattern in `content/router.py:get_lesson` and
    `media/router.py:get_signed_url`.
    """
    sb = _supabase(lesson_owner=OTHER_USER_ID)
    resp = _post(sb)

    assert resp.status_code == 404, resp.text
    assert sb.inserted == [], "no session may be created for a lesson the user does not own"


@pytest.mark.unit
def test_a_missing_lesson_returns_the_same_404_as_an_unowned_one(mock_to_thread: None) -> None:
    """**The enumeration-oracle assertion.** Status AND body must match, or the
    difference itself tells an attacker which lesson ids exist.
    """
    missing = _post(_supabase(lesson_owner=None))
    unowned = _post(_supabase(lesson_owner=OTHER_USER_ID))

    assert missing.status_code == unowned.status_code == 404
    assert missing.json() == unowned.json(), (
        "a missing lesson and an unowned lesson must be indistinguishable — "
        f"got {missing.json()} vs {unowned.json()}"
    )


# ── AC-5: re-learning yields a NEW session ───────────────────────────────────


@pytest.mark.unit
def test_the_same_user_starting_the_same_lesson_again_gets_a_new_session(
    mock_to_thread: None,
) -> None:
    """Sessions are attempt-scoped, not lesson-scoped — `analytics` and the CES
    history depend on it. No unique constraint on (user_id, lesson_id), and no
    reuse-if-exists shortcut.

    Uses ONE store across both calls. An earlier version used two independent
    stubs, which meant a reuse-if-exists implementation would look up an empty
    store, find nothing, and insert anyway — the test could not have failed.
    Mutation testing surfaced that; this version shares state so a lookup would
    actually find the first session.
    """
    minted: list[str] = []
    sessions: dict[str, dict[str, Any]] = {}
    sb = MagicMock()

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "lessons":
            (
                t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
            ) = {"lesson_id": LESSON_ID, "user_id": USER_ID}
        elif name == "sessions":

            def _insert(payload: dict[str, Any]) -> MagicMock:
                sid = f"session-{len(sessions) + 1}"
                row = {"session_id": sid, "started_at": "2026-07-29T12:00:00+00:00", **payload}
                sessions[sid] = row
                minted.append(sid)
                ex = MagicMock()
                ex.execute.return_value.data = [row]
                return ex

            t.insert.side_effect = _insert

            # A reuse-if-exists implementation would look here and find the first
            # session. Serving it is what makes this test able to fail.
            def _eq(_col: str, value: str) -> MagicMock:
                chain = MagicMock()
                found = [
                    r for r in sessions.values() if value in (r.get("user_id"), r.get("lesson_id"))
                ]
                chain.maybe_single.return_value.execute.return_value.data = (
                    found[0] if found else None
                )
                chain.eq.return_value = chain
                chain.execute.return_value.data = found
                return chain

            t.select.return_value.eq.side_effect = _eq
        return t

    sb.table.side_effect = _table

    first = _post(sb)
    second = _post(sb)

    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert first.json()["session_id"] != second.json()["session_id"], (
        "re-learning the same lesson must produce a NEW session, not reuse the first"
    )
    assert len(minted) == 2, f"expected two INSERTs, got {len(minted)} — a reuse shortcut?"


# ── AC-4: an unminted id must still 404 ──────────────────────────────────────


@pytest.mark.unit
def test_grade_quiz_still_rejects_a_session_id_that_was_never_minted() -> None:
    """**The assertion that stops the tempting wrong fix.**

    Creating the row lazily inside `submit_quiz` when it is missing would remove
    the 404 without fixing anything: `started_at` would become the time of the
    first answer, and any client-chosen UUID would silently become valid. The
    identity problem would be buried rather than solved.
    """
    import asyncio
    from unittest.mock import patch

    from fastapi import HTTPException

    from app.modules.assessment.service import grade_quiz

    sb = MagicMock()
    (
        sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
    ) = None

    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return func(*args, **kwargs)

    async def _run() -> None:
        with patch("app.modules.assessment.service.asyncio.to_thread", new=_sync_shim):
            await grade_quiz(
                session_id="never-minted-by-anyone",
                lesson_id=LESSON_ID,
                segment_id="seg_0",
                answers=[],
                user_id=USER_ID,
                supabase=sb,
            )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_run())

    assert exc.value.status_code == 404, (
        "an id that was never minted must still 404 — the fix must not become "
        "'accept any session id'"
    )


# ── AC-3: the demo path, end to end ──────────────────────────────────────────


@pytest.mark.unit
def test_a_minted_session_is_accepted_by_grade_quiz_ownership_check() -> None:
    """**The assertion that matters** (story AC-3).

    A test that only checks "insert was called" proves nothing — that is exactly
    the mock-shaped verification that let D18 survive (BD-2). This wires the two
    halves together: mint a session through the endpoint, then hand the returned
    id to `grade_quiz`'s ownership check with a store that only knows about rows
    the endpoint actually created.

    Before this story the ownership check raised 404 here, because nothing ever
    created the row. That 404 is the demo blocker.
    """
    import asyncio
    from unittest.mock import patch

    from fastapi import HTTPException

    from app.modules.assessment.service import create_session, grade_quiz

    # A tiny stand-in store: the endpoint writes to it, grade_quiz reads from it.
    store: dict[str, dict[str, Any]] = {}

    sb = MagicMock()

    # The lessons stub must be complete enough that a PASSING session check leads
    # somewhere distinguishable. grade_quiz's step 2 also 404s when the lesson has
    # no `content`, and an earlier version of this test could not tell the two
    # 404s apart — it would have "passed as red" for the wrong reason.
    lesson_content = {
        "segments": [
            {
                "segment_id": "seg_0",
                "quiz": [
                    {
                        "question_id": "q1",
                        "question": "?",
                        "options": ["a", "b"],
                        "correct_index": 0,
                    }
                ],
            }
        ]
    }

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "lessons":
            (
                t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data
            ) = {"lesson_id": LESSON_ID, "user_id": USER_ID, "content": lesson_content}
        elif name == "sessions":

            def _insert(payload: dict[str, Any]) -> MagicMock:
                row = {
                    "session_id": MINTED_SESSION_ID,
                    "started_at": "2026-07-29T12:00:00+00:00",
                    **payload,
                }
                store[MINTED_SESSION_ID] = row
                ex = MagicMock()
                ex.execute.return_value.data = [row]
                return ex

            t.insert.side_effect = _insert

            def _eq(_col: str, value: str) -> MagicMock:
                chain = MagicMock()
                chain.maybe_single.return_value.execute.return_value.data = store.get(value)
                return chain

            t.select.return_value.eq.side_effect = _eq
        return t

    sb.table.side_effect = _table

    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        return func(*args, **kwargs)

    async def _run() -> str:
        with patch("app.modules.assessment.service.asyncio.to_thread", new=_sync_shim):
            created = await create_session(lesson_id=LESSON_ID, user_id=USER_ID, supabase=sb)
            session_id = created["session_id"]

            # Now the demo path: submit a quiz with the id the server just minted.
            # An empty answers list raises 422 — that is FINE and is the proof we
            # want: 422 means the ownership check PASSED and validation was
            # reached. A 404 would mean the session was still not found.
            try:
                await grade_quiz(
                    session_id=session_id,
                    lesson_id=LESSON_ID,
                    segment_id="seg_0",
                    answers=[],
                    user_id=USER_ID,
                    supabase=sb,
                )
            except HTTPException as exc:
                return f"{exc.status_code}"
            return "200"

    outcome = asyncio.run(_run())

    assert outcome != "404", (
        "a session minted by the endpoint was still rejected as not found — "
        "D18 is not actually fixed"
    )
    assert outcome == "422", (
        f"expected to reach answer validation (422), got {outcome} — the ownership "
        "check should have passed for a minted session"
    )


# ── A failed insert must not look like success ───────────────────────────────


@pytest.mark.unit
def test_an_insert_that_returns_no_row_is_a_500_not_a_crash(mock_to_thread: None) -> None:
    """Found by mutation testing: removing the `if not created` guard survived
    the whole suite.

    Without it, `created[0]` raises IndexError — an unhandled 500 with a stack
    trace instead of a deliberate one, and no log line naming the lesson. The
    client cannot tell "the session was not created" from "the server broke",
    which is exactly the ambiguity D18 lived inside for weeks.
    """
    sb = _supabase(insert_returns=[])
    resp = _post(sb)

    assert resp.status_code == 500, resp.text
    assert resp.json()["detail"] == "Could not create session."
