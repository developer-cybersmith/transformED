---
id: "S3-43"
title: "WebSocket JWT auth — reject unauthenticated connections (HS256 pin, D80)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev4
priority: P0
defect_ref: D80
branch: sprint3/s3-43-ws-jwt-hs256-pin
decisions_covered: D80
depends_on: []
migration: "NO — sessions.user_id already exists in 20260611000000_initial_schema.sql"
---

# Story S3-43 — WebSocket JWT auth: reject unauthenticated connections (HS256 pin, D80)

## Context

`websocket_endpoint` in `apps/api/app/core/websocket.py` performs only a UUID format check on
`session_id` (line 145: `if not _SESSION_ID_RE.match(session_id): await websocket.close(code=4003)`).
There is no JWT verification, no session ownership check, and no check that the connecting client
is the student who owns the session.

**Story 4-1 explicitly scoped this out:** *"the WebSocket endpoint (`core/websocket.py`
`/ws/{session_id}`) does NOT use `CurrentUser` and currently performs no JWT verification — its
auth is a separate, not-yet-implemented concern."* This story implements that concern.

Any client that knows or guesses a valid UUID-format `session_id` can:
- Connect and receive `state_change`, `intervention`, and `lesson_ready` messages for that session
- Send client-drivable lifecycle events (`segment_complete`, `quiz_complete`, `teachback_complete`,
  `lesson_complete`) that advance the FSM and trigger `finalize_session` prematurely
- Receive CES-correlated timing information via `attention_ack`

This is D80 (Session IDOR) and is a P0 security fix. The `sprint3/s3-43-ws-jwt-hs256-pin`
branch implements the fix.

**HS256 pin rationale:** The HTTP `get_current_user` in `dependencies.py` branches on the
unverified token `alg` header — HS256 → local verify, otherwise → JWKS. D80 registers this
header-trust as a vulnerability in the WebSocket path: a malicious client can craft a token with
`"alg": "RS256"` in the header, causing the server to attempt JWKS verification instead of the
expected local HS256 check. The WebSocket handshake pins HS256 exclusively, verifying only against
`settings.supabase_jwt_secret`, regardless of what the `alg` header claims. Supabase JS client
tokens in the current project are HS256; JWKS verification is explicitly excluded.

## Story

As the system,
I want every WebSocket connection to `/ws/{session_id}` to be authenticated by a valid,
HS256-signed JWT passed in the `?token=` query parameter AND to verify that the authenticated
user owns the requested session,
so that a student or attacker cannot connect to, advance, or eavesdrop on another user's
session by guessing or obtaining a valid session UUID.

---

## Acceptance Criteria

### Authentication gate — absent or malformed token

- **AC 1.** A WebSocket connection to `/ws/{session_id}` with **no `?token` query parameter**
  is closed with WebSocket code **4001** before `websocket.accept()` is called. The connection
  is never accepted.
- **AC 2.** A WebSocket connection with a `?token` value that is not a valid JWT (e.g. `"not-a-jwt"`,
  empty string, or `"Bearer <token>"` with the `Bearer ` prefix) is closed with code **4001**
  before `websocket.accept()`.
- **AC 3.** A WebSocket connection with a **syntactically valid but expired** JWT (valid signature,
  `exp` in the past) is closed with code **4001** before `websocket.accept()`.
- **AC 4.** A WebSocket connection with a **JWT signed by the wrong secret** (correct HS256 format,
  wrong key) is closed with code **4001** before `websocket.accept()`.
- **AC 5.** A WebSocket connection with a **JWT missing a required claim** (`sub`, `exp`, or `iat`
  absent) is closed with code **4001** before `websocket.accept()`.

### HS256 algorithm pin

- **AC 6.** A JWT with `"alg": "RS256"` or `"alg": "ES256"` in its (unverified) header is
  **rejected with code 4001** — the server does NOT attempt JWKS verification; it decodes only
  with `algorithms=["HS256"]` against `settings.supabase_jwt_secret`. The `alg` header is never
  trusted to redirect to a different verification path.
- **AC 7.** The PyJWT `decode()` call specifies `algorithms=["HS256"]` as a hard-coded literal —
  not a variable, not sourced from the token header, not from settings. Confirmed by source
  inspection: no code path in `websocket.py`'s token verification ever passes an algorithm other
  than `HS256`.

### Session ownership check

- **AC 8.** After a valid HS256 JWT is verified, the server queries `sessions` for the given
  `session_id` and compares `sessions.user_id` against `jwt_payload["sub"]`. If the session does
  not exist, or `user_id != sub`, the connection is closed with code **4003** before
  `websocket.accept()`.
- **AC 9.** A valid JWT for user A attempting to connect to a session owned by user B is closed
  with code **4003** (ownership mismatch). User A gets neither the session state nor any
  intervention messages from user B's session.
- **AC 10.** The ownership query is a **single-row primary-key lookup**:
  `SELECT user_id FROM sessions WHERE session_id = <uuid>`. It carries no `.limit()` call
  because the primary key guarantees at most one row — this is `# BOUNDED: PK lookup` per
  `tests/unit/test_unbounded_queries.py` convention.

### Successful connection

- **AC 11.** A WebSocket connection with a valid HS256 JWT **and** matching session ownership
  (`jwt_payload["sub"] == sessions.user_id`) results in `websocket.accept()` being called and the
  existing session bootstrap running (reconnect restore or fresh init), exactly as before this story.
- **AC 12.** The existing UUID format check (`_SESSION_ID_RE`) still runs **before** the token
  check. A malformed UUID closes with code **4003** without attempting token verification (no DB
  read, no JWT decode).

### No remote call

- **AC 13.** Token verification is **local only** — no network call is made during the WebSocket
  handshake. Verified by asserting that no HTTP client or JWKS client is invoked during the auth
  path in tests.

### Audience claim

- **AC 14.** The PyJWT `decode()` call specifies `audience="authenticated"` — matching the
  `aud` claim Supabase embeds in every access token. A token without `"aud": "authenticated"` is
  rejected with code 4001.

### Error observability

- **AC 15.** All rejection paths log at **WARNING** level with `session_id` (truncated to first 8
  chars) and the rejection reason (no token / invalid token / expired / ownership mismatch). No
  full JWT string is logged. No `sub` value from an unverified token is logged.

---

## Dev Notes

### Files to change

| File | Change |
|------|--------|
| `apps/api/app/core/websocket.py` | Add auth gate at the top of `websocket_endpoint` |
| `apps/api/app/dependencies.py` | Extract `verify_ws_token(token, settings)` helper OR inline in websocket.py |
| `apps/api/tests/test_ws_jwt_auth.py` | CREATE — all AC tests |

### Token delivery

WebSocket clients cannot send custom HTTP headers on the initial upgrade request in all browsers.
The token is therefore passed as a **query parameter**: `wss://api.example.com/ws/{session_id}?token=<JWT>`.

Dev 2 must update the WebSocket client (`apps/web/src/lib/websocket.ts` or equivalent) to append
`?token=${supabase.auth.session().access_token}` to the WebSocket URL before connecting.

### Implementation sketch (websocket_endpoint)

```python
@ws_router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    # Gate 1: UUID format (existing)
    if not _SESSION_ID_RE.match(session_id):
        await websocket.close(code=4003)
        return

    # Gate 2: JWT presence and HS256 verification (NEW)
    token = websocket.query_params.get("token", "")
    try:
        payload = _verify_ws_token(token)  # raises on any failure
    except _WsAuthError:
        await websocket.close(code=4001)
        return

    # Gate 3: Session ownership (NEW)
    owner_id = await _get_session_owner(session_id)  # returns None if not found
    if owner_id is None or owner_id != payload.get("sub"):
        await websocket.close(code=4003)
        return

    # Existing connection flow
    await manager.connect(websocket, session_id)
    ...
```

### `_verify_ws_token` — HS256 pin

```python
def _verify_ws_token(token: str) -> dict[str, Any]:
    """Verify a WebSocket token. HS256 only — never consults JWKS.

    Raises _WsAuthError on any failure.
    """
    if not token:
        raise _WsAuthError("no token")
    from app.config import get_settings  # lazy
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],  # PINNED — never read from header
            audience="authenticated",
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError:
        raise _WsAuthError("expired") from None
    except jwt.InvalidTokenError:
        raise _WsAuthError("invalid") from None
```

### `_get_session_owner` — single-row PK lookup

```python
async def _get_session_owner(session_id: str) -> str | None:
    """Return sessions.user_id for the given session_id, or None if absent.
    # BOUNDED: PK lookup — at most 1 row
    """
    try:
        from app.core.db import get_supabase  # lazy
        import asyncio
        result = await asyncio.to_thread(
            lambda: get_supabase()
                .table("sessions")
                .select("user_id")
                .eq("session_id", session_id)
                .maybe_single()
                .execute()
        )
        return result.data["user_id"] if result.data else None
    except Exception:
        logger.warning("session owner lookup failed for %s — rejecting", session_id[:8])
        return None  # fail-closed: unknown ownership → reject
```

### DB

No migration required. `sessions.user_id uuid NOT NULL` already exists in
`supabase/migrations/20260611000000_initial_schema.sql:176`.

### Supabase client

Use the service-role client (bypasses RLS) since this is a server-to-server ownership check, not
a user-initiated query. The application code enforces `user_id == sub` — RLS is not the guard here.

---

## Tasks / Subtasks

### Task 1 — Story file (this commit)
- [ ] 1.1 Create `docs/stories/S3-43-websocket-jwt-auth-reject-unauthenticate.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-43-ws-jwt-hs256-pin`
- [ ] 1.3 Push to remote

### Task 2 — RED phase (failing tests first)
- [ ] 2.1 Create `apps/api/tests/test_ws_jwt_auth.py`
- [ ] 2.2 `test_no_token_param_closes_4001` (AC 1)
- [ ] 2.3 `test_malformed_token_closes_4001` (AC 2)
- [ ] 2.4 `test_expired_token_closes_4001` (AC 3)
- [ ] 2.5 `test_wrong_secret_closes_4001` (AC 4)
- [ ] 2.6 `test_missing_sub_claim_closes_4001` (AC 5)
- [ ] 2.7 `test_missing_iat_claim_closes_4001` (AC 5)
- [ ] 2.8 `test_rs256_header_token_closes_4001_not_jwks` (AC 6)
- [ ] 2.9 `test_es256_header_token_closes_4001_not_jwks` (AC 6)
- [ ] 2.10 `test_algorithm_pinned_hs256_literal_in_source` (AC 7 — source inspection)
- [ ] 2.11 `test_ownership_mismatch_closes_4003` (AC 9)
- [ ] 2.12 `test_session_not_found_closes_4003` (AC 8)
- [ ] 2.13 `test_valid_token_matching_owner_accepts` (AC 11)
- [ ] 2.14 `test_invalid_uuid_closes_4003_before_token_check` (AC 12 — DB mock never called)
- [ ] 2.15 `test_no_network_call_during_auth` (AC 13)
- [ ] 2.16 `test_audience_required` (AC 14)
- [ ] 2.17 `test_rejection_logs_warning_with_truncated_session_id` (AC 15)
- [ ] 2.18 Confirm all tests FAIL (RED)

### Task 3 — GREEN phase (implementation)
- [ ] 3.1 Add `_WsAuthError` sentinel exception to `websocket.py`
- [ ] 3.2 Implement `_verify_ws_token(token)` — HS256 pin, no JWKS path
- [ ] 3.3 Implement `_get_session_owner(session_id)` — `asyncio.to_thread` PK lookup, fail-closed
- [ ] 3.4 Add auth gate at top of `websocket_endpoint` (UUID check → token verify → ownership check)
- [ ] 3.5 Add WARNING logs for each rejection path (truncated session_id, no JWT data logged)
- [ ] 3.6 Confirm all 17 tests PASS (GREEN)

### Task 4 — REFACTOR + validation
- [ ] 4.1 `ruff check apps/api/app/core/websocket.py apps/api/tests/test_ws_jwt_auth.py`
- [ ] 4.2 `ruff format --check apps/api/app/core/websocket.py apps/api/tests/test_ws_jwt_auth.py`
- [ ] 4.3 Full regression suite: `pytest apps/api/tests/ -v` — 0 regressions
- [ ] 4.4 Source scan: confirm `algorithms=["HS256"]` is a literal in `websocket.py`, not a variable

### Task 5 — 6-agent adversarial code review
- [ ] 5.1 Layer 1 — Story Quality: all ACs testable, story-first gate verified
- [ ] 5.2 Layer 2 — Blind Hunter: algorithm confusion, token replay, log injection, UUID traversal
- [ ] 5.3 Layer 3 — Test Coverage: all ACs have tests, no vacuous mock assertions
- [ ] 5.4 Layer 4 — AC Completeness: every AC maps to ≥1 named test
- [ ] 5.5 Layer 5 — Process Integrity: no hardcoded secrets, no remote calls in auth path
- [ ] 5.6 Layer 6 — Scale & Load: ownership query bounded, no fan-out in auth path

### Task 6 — Dev 2 notification + commit
- [ ] 6.1 Notify Dev 2 that WS URL must include `?token=<access_token>` query parameter
- [ ] 6.2 Final commit on `sprint3/s3-43-ws-jwt-hs256-pin`
- [ ] 6.3 Push to remote
- [ ] 6.4 Update `docs/DEFECT-REGISTER.md` — move D80 to CLOSED with enforcement

---

## Scale & Load

### Q1. What is ONE unit of work, and what is its range?

One WebSocket authentication attempt during the upgrade handshake. The work is:
1. One JWT decode (in-process, no I/O) — constant time regardless of token content.
2. One DB read: `SELECT user_id FROM sessions WHERE session_id = ?` — single PK lookup.

Min: 0 ms (UUID format check fails, no token decode, no DB read).
Typical: ~2 ms (JWT decode ~0.1 ms + Supabase PK lookup round-trip ~1-2 ms).
Largest measured: not yet measured; bounded by Supabase PK lookup SLA (~5 ms p99).
Beyond the limit: N/A — the operation either succeeds or fails; there is no variable-size loop.

### Q2. Which budgets are FIXED while the input VARIES — and what happens past them?

| Budget | Fixed value | What happens past it |
|--------|-------------|----------------------|
| Token size accepted by PyJWT | ~8 KB (JWT spec) | `jwt.DecodeError` → rejected with 4001 before DB query |
| DB rows returned by ownership query | 1 (primary key) | Impossible to exceed — PK guarantees ≤1 row |
| Auth timeout | Inherits from Supabase client default (~5 s) | Connection attempt times out; websocket.close(4001) in the exception handler |

No silent truncation: all budget overruns raise explicit errors that reject the connection.

### Q3. What is the SCOPE of every limit?

| Limit | Scope |
|-------|-------|
| JWT decode (PyJWT) | Per-connection, per-process (stateless) |
| DB query (`sessions` PK lookup) | Per-connection, per-deployment (shared Supabase Postgres) |
| Supabase service-role client connection pool | Per-instance (Railway single replica today; see D49) |

No limit is keyed by IP or shared across users — each connection authenticates independently.
The session ownership query is a read on a table with an indexed PK; it does not contend with write
paths even under concurrent connections to the same session_id.

### Q4. Which reads and writes are UNBOUNDED?

None introduced by this story.
- The ownership query is `SELECT user_id FROM sessions WHERE session_id = <uuid>` — single PK
  lookup, bounded at 1 row. Comment `# BOUNDED: PK lookup` satisfies `test_unbounded_queries.py`.
- No fan-out: one connection → one auth attempt.
- No writes in the auth path.

### Q5. Which caps were INHERITED from an earlier design, and have they been re-derived?

The UUID format check (`_SESSION_ID_RE`) was the only prior gate. It was sized for the task of
preventing Redis key-namespace traversal (noted in the existing comment at line 37). That purpose
is unchanged and the gate still runs first. No inherited cap is invalidated by adding JWT auth.

The 30-second `asyncio.wait_for` in the receive loop (Story S3-40, D9) is downstream of `connect()`,
which is downstream of auth. It is not affected by this story.

### Q6. Is every check-then-act sequence safe under CONCURRENT requests?

The auth sequence is:
1. Read `sessions.user_id` (read-only PK lookup)
2. Compare to `jwt_payload["sub"]` (in-process, no write)
3. Call `websocket.accept()` or `websocket.close()`

This is a pure read+compare: no write follows the check. Two concurrent connections for the same
session_id both read the same `sessions.user_id` value; both get accepted or rejected identically.
There is no TOCTOU window because no write occurs between read and act.

The only potential race: a session is deleted between the ownership read and `websocket.accept()`.
Effect: the session bootstrap (`_restore_or_init_session`) handles a missing session gracefully
(initialises fresh state). This is the same race that existed before this story; the auth gate does
not make it worse.

---

## Security

### Threat model

| Threat | Mitigation |
|--------|------------|
| Unauthenticated connection (no JWT) | Closed 4001 before accept() |
| Stolen session_id (guessed UUID) | Ownership check: `sessions.user_id == jwt_payload.sub` (code 4003) |
| JWT from a different user | Ownership check fails → 4003 |
| Expired JWT | `jwt.ExpiredSignatureError` → 4001 |
| Algorithm confusion (`alg: none`, RS256, ES256) | Hard-coded `algorithms=["HS256"]` — header value ignored |
| JWKS redirect (D80 class) | HS256 pin: JWKS client is never instantiated in the WS auth path |
| JWT replay (token reuse after revocation) | Accepted limitation — PyJWT verifies `exp` only; no revocation list in MVP |
| Log injection via JWT claims | Token string never logged; `session_id` logged as first 8 chars only |

### Auth boundary

The WebSocket auth gate is **pre-accept**: `websocket.close()` is called before `websocket.accept()`.
This means:
- The connection is never registered in `ConnectionManager._connections`
- The session bootstrap (`_init_session_state`, `_restore_or_init_session`) never runs
- No Redis keys are created for the unauthenticated session
- No `session_events` row is created

### IDOR class closure

D80 closes the BOLA/IDOR vulnerability described in OWASP API Security Top 10 2023, API1:2023.
After this story, the WebSocket endpoint has the same authentication guarantee as all HTTP routes
that use `CurrentUser` — local JWT verification + ownership proof.

### Dev 2 breaking change

The WebSocket URL changes from `wss://host/ws/{session_id}` to
`wss://host/ws/{session_id}?token=<access_token>`. Dev 2 must update the client before this
branch lands on `main`. The token expires with the Supabase access token (typically 1 hour); the
client should refresh the token before reconnecting after expiry.

---

## Test Requirements

All tests live in `apps/api/tests/test_ws_jwt_auth.py`. Each must be `@pytest.mark.unit`.

### Test harness

Build a minimal FastAPI app mounting `ws_router` with `get_settings` overridden to a
`MagicMock(supabase_jwt_secret=_SECRET, ...)`. Mock `_get_session_owner` to return a controllable
`user_id`. Use `starlette.testclient.TestClient` with `with client.websocket_connect(...)` raising
on rejection codes.

### Token helper

```python
_SECRET = "test-jwt-secret"
_UID = "user-abc-123"

def _token(secret=_SECRET, uid=_UID, **overrides):
    now = 1_700_000_000
    claims = {"sub": uid, "aud": "authenticated", "iat": now, "exp": now + 3600}
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")
```

### Test names and AC coverage

| Test name | AC |
|-----------|-----|
| `test_no_token_param_closes_4001` | AC 1 |
| `test_empty_token_param_closes_4001` | AC 2 |
| `test_bearer_prefix_token_closes_4001` | AC 2 |
| `test_not_a_jwt_string_closes_4001` | AC 2 |
| `test_expired_token_closes_4001` | AC 3 |
| `test_wrong_secret_closes_4001` | AC 4 |
| `test_missing_sub_claim_closes_4001` | AC 5 |
| `test_missing_iat_claim_closes_4001` | AC 5 |
| `test_rs256_alg_header_closes_4001_no_jwks_attempt` | AC 6 |
| `test_es256_alg_header_closes_4001_no_jwks_attempt` | AC 6 |
| `test_hs256_literal_in_source` | AC 7 — inspect `websocket.py` source for `algorithms=["HS256"]` |
| `test_session_not_found_closes_4003` | AC 8 |
| `test_ownership_mismatch_closes_4003` | AC 9 |
| `test_ownership_query_is_pk_bounded` | AC 10 — assert `# BOUNDED: PK lookup` comment present |
| `test_valid_token_matching_owner_connects` | AC 11 |
| `test_invalid_uuid_closes_4003_no_db_call` | AC 12 — DB mock asserts not called |
| `test_no_jwks_client_instantiated_during_auth` | AC 13 |
| `test_missing_aud_claim_closes_4001` | AC 14 |
| `test_rejection_logs_warning_not_full_token` | AC 15 |

### Source inspection tests

`test_hs256_literal_in_source` and `test_ownership_query_is_pk_bounded` are source-inspection
tests (read `websocket.py` as text, assert literal presence) to guard against drift per
CLAUDE.md binding rule 7 and the `test_node_return_shape.py` precedent.

---

## Migration

**NO.** `sessions.user_id uuid NOT NULL` already exists in
`supabase/migrations/20260611000000_initial_schema.sql:176`. No schema change is required.

---

## Decision References

- **D80** (DEFECT-REGISTER.md): "JWT WebSocket auth selects HS256 vs JWKS based on unverified
  `alg` header" — this story pins HS256 and closes D80.
- **Decision D7** (docs/architecture/CES_DECISION_RECORD.md §11): "WebSocket Endpoint Has No
  Authentication" — Option B selected: JWT in `?token=` query param, HS256 verify, ownership check.
- **Story 4-1** (docs/stories/4-1-jwt-auth-tests.md): Explicitly deferred WS auth — *"its auth
  is a separate, not-yet-implemented concern"*. This story implements it.
- **D16** (approved merge order): s3-42 → main, **s3-43** → main, s3-44 → main, ces-fallback → main.

---

## Senior Developer Review

*(populated after 6-agent review — Task 5)*

---

## Dev Agent Record

### Implementation Plan

1. Add `_WsAuthError` + `_verify_ws_token()` + `_get_session_owner()` to `websocket.py`
2. Insert auth gate at top of `websocket_endpoint` after UUID check
3. Add WARNING log helpers — no JWT strings, no `sub` from unverified tokens
4. Tests: 19 tests covering all 15 ACs, including 2 source-inspection tests
5. Update DEFECT-REGISTER.md: D80 → CLOSED with enforcement = `test_ws_jwt_auth.py`

### Debug Log

*(populated during implementation)*

### Completion Notes

*(populated on completion)*

### File List

*(populated on completion)*

### Change Log

*(populated on completion)*
