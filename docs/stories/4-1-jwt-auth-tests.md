---
baseline_commit: "ed7089edb80b95ad59e95d69153ce6beae7b033f"
---

# Story 4-1: JWT Middleware Live and Tested on All Routes

**Status:** in-progress

---

## Story

As Dev 4 (WebSocket / JWT / tutor owner),
I want an integration test suite proving `get_current_user` rejects missing, expired, malformed,
and unsigned-claim JWTs while accepting valid ones,
so that the Sprint 1 `jwt_all_routes` task is closed and every `CurrentUser`-protected route
is verifiably gated by local JWT verification (no remote auth call).

---

## Context

`get_current_user` in `apps/api/app/dependencies.py` is fully implemented:
- `jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], options={"require": ["sub", "exp", "iat"]})`
- `ExpiredSignatureError` → HTTP 401 ("Token has expired")
- `InvalidTokenError` → HTTP 401 ("Could not validate credentials")
- Empty `sub` claim → HTTP 401
- `HTTPBearer(auto_error=True)` → missing/blank Authorization header is rejected before the handler runs

Eight routers inject `CurrentUser` (analytics, tutor, admin, content, auth, media, assessment). The
verification logic is shared and identical across all of them, so a focused test of `get_current_user`
— plus one test mounting a real module router (tutor) — proves the contract for every
`CurrentUser`-protected **HTTP** route.

**Out of scope:** the WebSocket endpoint (`core/websocket.py` `/ws/{session_id}`) does NOT use
`CurrentUser` and currently performs no JWT verification — its auth is a separate, not-yet-implemented
concern. This story covers HTTP route enforcement only and does not claim to cover the WS handshake.

**Gap:** No `tests/test_auth.py` exists anywhere in the codebase. The tracker marks this task **Partial**
(implementation done, tests missing). This story adds the tests only — no production code changes.

---

## Acceptance Criteria

- **AC 1:** A request to a `CurrentUser`-protected route with **no Authorization header** → HTTP 401 or 403
  (HTTPBearer `auto_error` fires before business logic).
- **AC 2:** A request with a **valid, correctly-signed** token carrying `sub`, `exp` (future), `iat` → HTTP 200,
  and the decoded `sub` is available to the handler.
- **AC 3:** A request with an **expired** token (valid signature, `exp` in the past) → HTTP 401.
- **AC 4:** A request with a token **signed by the wrong secret** → HTTP 401.
- **AC 5:** A request with a **malformed / non-JWT** bearer string → HTTP 401.
- **AC 6:** A request with a **valid signature but missing a required claim** (e.g. no `sub`, or no `iat`)
  → HTTP 401 (proves `options={"require": [...]}` is enforced, not just signature).
- **AC 7:** Verification is **local only** — no test requires network; tokens are minted in-test with PyJWT
  using a known secret injected via `get_settings` dependency override.

---

## Tasks / Subtasks

### Task 1 — Test harness

- [ ] 1.1 Build a minimal `FastAPI()` app with one route `GET /protected` depending on `CurrentUser`,
  returning `{"sub": current_user["sub"]}`.
- [ ] 1.2 Override the `get_settings` dependency to return a settings object whose
  `supabase_jwt_secret` is a known test constant — so tokens can be minted and verified locally.
- [ ] 1.3 Use `starlette.testclient.TestClient(app, raise_server_exceptions=False)`.
- [ ] 1.4 Helper `_token(**claims)` that mints an HS256 JWT with the test secret and merges default
  `sub`/`exp`/`iat` claims (override-able per test).

### Task 2 — Tests (one per AC)

- [ ] 2.1 `test_no_auth_header_rejected` — no header → 401 or 403 (AC 1)
- [ ] 2.2 `test_valid_token_returns_200` — valid token → 200, body `sub` matches (AC 2)
- [ ] 2.3 `test_expired_token_returns_401` — `exp` in past → 401 (AC 3)
- [ ] 2.4 `test_wrong_secret_returns_401` — signed with a different secret → 401 (AC 4)
- [ ] 2.5 `test_malformed_token_returns_401` — `"not-a-jwt"` bearer → 401 (AC 5)
- [ ] 2.6 `test_missing_sub_claim_returns_401` — valid sig, no `sub` → 401 (AC 6)
- [ ] 2.7 `test_missing_iat_claim_returns_401` — valid sig, no `iat` → 401 (AC 6, require list)

### Task 3 — Verify

- [ ] 3.1 Run `pytest tests/test_auth.py -v` → all green.
- [ ] 3.2 Run full suite → no regressions introduced by the new file.

---

## Dev Notes

### Files to Change

| File | Change type | What |
|------|-------------|------|
| `apps/api/tests/test_auth.py` | CREATE | Full JWT auth integration test file |

No production code changes. `dependencies.py` is already correct.

### Conventions to follow (from test_quiz_endpoint.py)

- `@pytest.mark.unit` on every test.
- `from __future__ import annotations` at top.
- Build app + `TestClient` at module level; mount the real `get_current_user` (do NOT override it —
  overriding it would bypass the very logic under test). Override only `get_settings`.
- `asyncio_mode = "auto"` is set in `pyproject.toml` — sync TestClient tests need no async marker juggling.

### Token minting

```python
import jwt
_SECRET = "test-jwt-secret"

def _token(secret: str = _SECRET, **overrides) -> str:
    now = 1_700_000_000  # fixed epoch — Date.now() not needed; tokens are self-contained
    claims = {"sub": "user-001", "iat": now, "exp": now + 3600}
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")
```

For the expired-token test, set `exp` to `now - 10` and `iat` to `now - 3600`. PyJWT validates `exp`
against the real current time, so a fixed past epoch reliably expires.

### Settings override

```python
def _fake_settings():
    s = MagicMock()
    s.supabase_jwt_secret = _SECRET
    return s

app.dependency_overrides[get_settings] = _fake_settings
```

Note: override the SAME `get_settings` callable that `dependencies.py` imports
(`from app.config import get_settings`). FastAPI keys overrides by the function object, so importing
`get_settings` from `app.dependencies` or `app.config` resolves to the same object — either works.

### Non-negotiable rules (CLAUDE.md §18)

- JWT verified locally (PyJWT + secret) — NEVER a remote auth call. Tests must not hit any network.
- Algorithms restricted to `["HS256"]` — do not test or enable `none`/RS256 paths.
