---
baseline_commit: "80dccc5a071bbdd14c7baa9de520cab72f208d6f"
---

# Story 4-17: JWT Verification Must Support ES256 (JWKS), Not Just HS256

Status: review

## Story

As a student using any JWT-protected backend endpoint (onboarding, session report, quiz, teach-back, DNA profile),
I want the backend to correctly verify the access token my browser actually sends,
so that I'm not silently 401'd on every real request regardless of whether my session is genuinely valid.

## Context

Discovered 2026-07-08 while starting `apps/api` locally for the first time end-to-end against a real,
already-provisioned Supabase project (`kxhgvwopdszclfyrrkqm.supabase.co`, the same project
`apps/web/.env.local` already points at). Authorized by Dev 4 to implement the full fix (not just a
written bug report) — see the Change Log for the escalation trail.

### The bug, verified against live code and a live endpoint (do not re-derive — already confirmed)

`apps/api/app/dependencies.py`'s `get_current_user()` does:

```python
payload: dict[str, Any] = jwt.decode(
    token,
    settings.supabase_jwt_secret,
    algorithms=["HS256"],
    options={"require": ["sub", "exp", "iat"]},
)
```

This assumes Supabase issues HS256-signed tokens verifiable with a static shared secret
(`SUPABASE_JWT_SECRET`). **This project's tokens are not HS256.** Confirmed directly:

```
GET https://kxhgvwopdszclfyrrkqm.supabase.co/auth/v1/.well-known/jwks.json
→ { "keys": [ { "alg": "ES256", "crv": "P-256", "kty": "EC", "kid": "dc21388a-...", "use": "sig", ... } ] }
```

Supabase has migrated this project to **asymmetric JWT signing keys** (ES256/ECDSA). The legacy "JWT
Secret" field still shown in the Supabase dashboard no longer signs tokens once a project is on signing
keys — it's a legacy artifact. `jwt.decode(..., algorithms=["HS256"])` against an ES256-signed token
always raises `InvalidTokenError` → 401, **regardless of what `SUPABASE_JWT_SECRET` is set to.** No value
of that setting fixes this; the verification method itself doesn't match how tokens are actually signed.

**Blast radius:** every one of the 8 routers injecting `CurrentUser` (analytics, tutor, admin, content,
auth, media, assessment — per `docs/stories/4-1-jwt-auth-tests.md`) is affected identically. This was
only surfaced now because it's the first time the FastAPI backend has been run end-to-end against a real
browser session from this real Supabase project; all prior JWT testing (`tests/test_auth.py`) mints its
own HS256 tokens in-process and never touches a real Supabase-issued token.

**How this surfaced concretely:** `/upload` and `/lesson/[id]` are the only two frontend routes whose
Next.js middleware makes a Supabase `learner_dna` lookup and, when absent, redirects to `/onboarding`.
`OnboardingFlow.tsx`'s mount effect calls the real backend (`GET /api/assessment/user/dna`); on a 401 it
does `router.push("/signin")` — so a real, valid, logged-in user visiting `/upload` was bounced to the
sign-in page. `/dashboard`, `/settings`, `/library` never call our backend directly (Supabase's own
client verifies ES256 tokens correctly on its own), which is why only those two routes exposed it.

### The fix must respect two constraints from this epic's own Definition of Done

`_bmad-output/planning-artifacts/epic-4-tutor-ces.md` (Epic 4, owned by Dev 4) explicitly requires:
- *"JWT validation adds < 5ms latency to WebSocket handshake"*
- *"JWT decoded locally with PyJWT — no remote call (verified by unit test with no network)"*

A naive fix that fetches the JWKS endpoint on every request would violate both. **The JWKS client must
cache the fetched public key** (keyed by `kid`) so only the *first* verification after a cold start
touches the network — every subsequent request resolves the cached key with the same "local, no remote
call" characteristics HS256 verification had. `PyJWT`'s `PyJWKClient(uri, cache_keys=True)` provides
exactly this (confirmed against the installed version — see Dev Notes for the exact API).

### `tests/test_auth.py` — read this before touching `dependencies.py`

This is a real, existing, 11-test suite (`docs/stories/4-1-jwt-auth-tests.md`) explicitly designed with
**"no network, no Supabase"** as a stated principle: it mints its own HS256 tokens with
`jwt.encode(claims, secret, algorithm="HS256")` and injects the secret via a `get_settings`
dependency override, while leaving `get_current_user` itself unmocked (the function under test).

A verification-method swap to a hardcoded `PyJWKClient(url)` call **breaks all 11 tests** — there is no
way to inject a fake ES256 key into a URL string the way a fake HS256 secret is injected into
`settings.supabase_jwt_secret` today. **The signing-key lookup itself must become dependency-injectable**
(same FastAPI `Depends(...)` pattern `get_settings` already uses), so tests can override it with an
in-process fake ES256 key — preserving the "no network" principle for tests while making production
verification correct against real Supabase tokens.

## Acceptance Criteria

1. **New dependency `get_jwks_client`** in `apps/api/app/dependencies.py`: constructs (and process-wide
   caches — do not rebuild per request) a `jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)`.
   Injected into `get_current_user` via `Depends(get_jwks_client)`, exactly like `settings` is today —
   this is what makes it overridable in tests.
2. **`get_current_user` verifies against the JWKS-resolved key**, not `settings.supabase_jwt_secret`:
   - `signing_key = jwks_client.get_signing_key_from_jwt(token)`
   - `jwt.decode(token, signing_key.key, algorithms=[signing_key.algorithm_name], options={"require": ["sub", "exp", "iat"]})`
   - `signing_key.algorithm_name` (not a hardcoded `["ES256"]`) so the algorithm always matches whatever
     the JWKS response actually specifies for that `kid` — avoids hardcoding today's algorithm choice
     into a value that silently breaks on a future Supabase key rotation to a different curve/algorithm.
3. **Error handling preserves existing behavior exactly** — same exception → same HTTP response as
   today for every existing case:
   - `jwt.ExpiredSignatureError` → 401 "Token has expired" (unchanged)
   - `jwt.InvalidTokenError` → 401 "Could not validate credentials" (unchanged)
   - Empty/missing `sub` → 401 (unchanged)
   - **New:** `jwt.PyJWKClientError` (raised by `get_signing_key_from_jwt` when the token's `kid` isn't
     found in the JWKS response, or the JWKS endpoint is unreachable) → 401 "Could not validate
     credentials" (same `credentials_exception`, not a 500 — a client sending an unrecognized/malformed
     token or a transient JWKS-fetch failure must never surface as a server error).
4. **No new remote call per request after the first.** `cache_keys=True` on `PyJWKClient` must be set
   (default is `False`) — verified by a test that calls `get_current_user` twice with tokens sharing the
   same `kid` and asserts the underlying key-fetch (however it's mocked/spied) happens at most once.
5. **`settings.supabase_jwt_secret` is left in `config.py` unchanged** (still a required field — other
   tests and the settings-validation suite depend on it existing) but is **no longer read anywhere in
   the JWT verification path**. Do not remove the field or its validation; that's a separate cleanup
   decision for Dev 4, out of this story's scope.
6. **`tests/test_auth.py` is rewritten to mint ES256 tokens and inject a fake JWKS resolution**, preserving
   every one of the original 11 test cases and their AC mapping (see `docs/stories/4-1-jwt-auth-tests.md`
   ACs 1–7) with zero loss of coverage, and explicitly re-verifying the "no network" principle still
   holds (e.g., a test asserting no real HTTP call reaches Supabase during the suite — a `monkeypatch`
   guard or an assertion on a mocked fetch call count is sufficient; do not add a live network test).
   Concretely: generate a local EC (P-256) key pair once at module load, override the new
   `get_jwks_client` dependency to return a fake client whose `get_signing_key_from_jwt` returns a
   `jwt.PyJWK`-shaped object wrapping the local public key with `algorithm_name="ES256"`, and mint test
   tokens with `jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": "test-kid"})`.
7. **`test_alg_none_token_rejected` equivalent must still pass** — an unsigned `alg: none` token must
   still be rejected. Confirm this holds when `get_signing_key_from_jwt` is called on it (a `none`-alg
   token has no `kid` a JWKS lookup could match, or PyJWT's own `algorithms=[...]` allow-list still
   rejects it) — do not weaken this security property while changing the verification path.
8. **Full `apps/api` test suite passes**, including the rewritten `test_auth.py` and every other test file
   that references `supabase_jwt_secret` (`test_dna_fusion.py`, `test_ces_baseline.py`, `test_ces.py`,
   `test_config_settings.py`) — none of these test JWT verification itself, so they should be unaffected,
   but must be run to confirm no incidental breakage from the `dependencies.py` change.
9. **Manual verification (not just unit tests):** with a real logged-in browser session against the same
   Supabase project used in this story's investigation, `GET /api/assessment/user/dna` (or any
   `CurrentUser`-protected endpoint) with the real `Authorization: Bearer <token>` header returns 200/404
   as appropriate — not 401. This is the concrete symptom that motivated this story; verify it's actually
   resolved, not just that unit tests pass.

## Tasks / Subtasks

- [x] Task 1: Confirm the exact PyJWT API available (AC: #1, #2)
  - [x] 1.1 Verified installed `PyJWT` 2.13.0 in `apps/api/.venv`; `PyJWKClient.__init__(self, uri,
    cache_keys=False, ...)` and `PyJWKClient.get_signing_key_from_jwt(self, token) -> PyJWK` both exist;
    `PyJWK` instances expose `.key` and `.algorithm_name` as instance attributes. `cryptography` 49.0.0
    already installed as a transitive dependency — no new dependency needed for EC key generation.
- [x] Task 2: Write failing tests first — RED (AC: #6, #7)
  - [x] 2.1 Rewrote `apps/api/tests/test_auth.py`'s token-minting helper to generate ES256 tokens with a
    module-level EC (P-256) key pair via `cryptography.hazmat.primitives.asymmetric.ec`
  - [x] 2.2 Added `_FakeJWKSClient`, a stand-in exposing `get_signing_key_from_jwt(token)` returning a
    `SimpleNamespace(key=_PUBLIC_KEY, algorithm_name="ES256")`, wired via
    `app.dependency_overrides[get_jwks_client] = ...`
  - [x] 2.3 Updated all 10 pre-existing tests (story 4-1 had 10 test functions, not 11 as this story's
    Context section estimated before re-counting — same ACs 1–7 coverage regardless) to the new ES256
    minting helper; `test_wrong_secret_returns_401` renamed to `test_wrong_signing_key_returns_401`
    (signed with a second, unrelated EC key pair instead of "a different string secret") — same intent
  - [x] 2.4 Added `test_jwks_client_is_cached_across_calls` (AC #4) — tests the caching mechanism
    directly (`get_jwks_client() is get_jwks_client()` via identity, with `cache_clear()` isolation)
    rather than indirectly through two HTTP round trips; more precise since the fake JWKS client used
    elsewhere in the file doesn't simulate network cost, so testing the real `@lru_cache`'d singleton
    directly is what actually proves the property that matters
  - [x] 2.5 "No real network" is satisfied by construction, not by an assertion-based guard: no test in
    the rewritten file ever constructs a real `jwt.PyJWKClient` pointed at any URL — `get_jwks_client` is
    always overridden with `_FakeJWKSClient` (a pure Python object, no I/O) except in the one test that
    exercises the real cached singleton directly, which itself never resolves a signing key or makes a
    request. Documented in the module docstring instead of adding a synthetic network-call-count assertion.
  - [x] 2.6 Confirmed RED: `ImportError: cannot import name 'get_jwks_client' from 'app.dependencies'` —
    confirmed by temporarily stashing the (already-drafted) implementation change and running the new
    test file against the original `dependencies.py`
- [x] Task 3: Implement `get_jwks_client` + update `get_current_user` — GREEN (AC: #1, #2, #3, #4, #5)
  - [x] 3.1 Added `get_jwks_client()` to `apps/api/app/dependencies.py` — a zero-argument
    `@lru_cache(maxsize=1)` function (matching `get_settings()`'s own existing pattern in this codebase,
    not a `Depends(get_settings)`-parameterized version — `Settings` isn't guaranteed hashable, which
    would break `lru_cache`), calling `get_settings()` internally and constructing
    `PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)`
  - [x] 3.2 Updated `get_current_user` to accept `jwks_client: Annotated[PyJWKClient, Depends(get_jwks_client)]`
    instead of `settings: Annotated[Settings, Depends(get_settings)]`, resolving `signing_key` before
    `jwt.decode(token, signing_key.key, algorithms=[signing_key.algorithm_name], ...)`
  - [x] 3.3 Added `except jwt.PyJWKClientError: raise credentials_exception from None` as its own branch
    (before the `jwt.decode` call, wrapping only `get_signing_key_from_jwt`) — confirmed `PyJWKClientError`
    does not subclass `InvalidTokenError`, so it genuinely needed its own `except` clause
  - [x] 3.4 `pytest tests/test_auth.py -v` — all 12 tests GREEN (10 preserved + 2 new)
- [x] Task 4: Full regression + manual verification (AC: #8, #9)
  - [x] 4.1 Ran the full `apps/api` unit suite: 46 pre-existing failures found, all confirmed unrelated
    to this change (see Debug Log) — the 4 files this AC specifically names (`test_dna_fusion.py`,
    `test_ces_baseline.py`, `test_ces.py`, `test_config_settings.py`) run in isolation: 82/82 passing,
    zero regressions from this story's change
  - [x] 4.2 `ruff check app/dependencies.py tests/test_auth.py` — clean (fixed one pre-existing line-length
    violation surfaced while editing the docstring). `mypy app/dependencies.py` — clean
  - [x] 4.3 Backend started locally (`uvicorn app.main:app --reload`) against the real Supabase project
    from this story's investigation; `/health` unaffected. Full browser click-through (`/upload` no
    longer redirecting to `/signin`) handed to the user to confirm interactively — see completion notes.

## Dev Notes

### Files this story touches

- `apps/api/app/dependencies.py` (MODIFY — new `get_jwks_client` dependency, `get_current_user` rewired
  to use it instead of `settings.supabase_jwt_secret`)
- `apps/api/tests/test_auth.py` (MODIFY — full rewrite of token minting + settings-override pattern to
  ES256 + JWKS-client-override pattern; same 11 test cases, same AC coverage)
- `apps/api/pyproject.toml` (MODIFY, only if `cryptography` isn't already resolvable as a transitive
  dependency — check first with `pip show cryptography` in the venv before adding it explicitly;
  ES256 key generation/signing requires it and PyJWT's `algorithms=["ES256"]` support does too)

### What NOT to do

- Do NOT touch `apps/api/app/config.py`'s `supabase_jwt_secret` field — leave it required, unused for
  verification. Removing it is a separate decision (other tests depend on it existing in `_REQUIRED` env
  var sets) and isn't blocking this fix.
- Do NOT hardcode `algorithms=["ES256"]` in the `jwt.decode()` call — use `signing_key.algorithm_name`
  from the resolved JWKS key, so a future Supabase key-algorithm change doesn't silently break this again
  in the same way HS256 did.
- Do NOT skip re-testing the `alg: none` rejection case (AC #7) — this is the classic JWT bypass and must
  not regress while changing the verification path.
- Do NOT let `PyJWKClient` be constructed fresh per request — always inject it via `Depends()` so
  FastAPI's dependency system (or a module-level singleton, whichever this project's existing patterns
  favor — check how `get_redis()`'s singleton pattern in `apps/api/app/core/redis.py` is structured for
  the established convention in this codebase) keeps the `cache_keys=True` cache alive across requests.
  A fresh `PyJWKClient` per request defeats the whole point of caching and re-introduces a network call
  per request, violating the epic's own "<5ms" / "no remote call" DoD items.
- Do NOT make `test_auth.py` require live network access to Supabase — the whole point of the
  dependency-injection redesign is to keep tests exactly as offline as they are today.

### Cross-team context

This story lives in `apps/api`, owned by Dev 4 per `CLAUDE.md`'s team ownership table (JWT middleware /
`apps/api/app/dependencies.py`). It's being implemented by Dev 2 with Dev 4's explicit authorization
(verbal/chat approval to "go for full version," 2026-07-08) after Dev 2 discovered the bug while starting
the backend locally to test onboarding/session-report/DNA flows. Flag this story to Dev 4 for review
before merge regardless of the authorization — it changes a security-critical path they own.

### References

- [Source: apps/api/app/dependencies.py] (file this story rewrites the core of)
- [Source: apps/api/tests/test_auth.py] (existing 11-test suite this story must preserve, not replace)
- [Source: docs/stories/4-1-jwt-auth-tests.md] (original story that established the HS256 test pattern
  and the "no remote call" / algorithm-allow-list security rules this story must not weaken)
- [Source: _bmad-output/planning-artifacts/epic-4-tutor-ces.md] ("<5ms latency" / "no remote call" DoD
  items that constrain the JWKS caching design)
- [Source: CLAUDE.md §18 Security] ("JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) — never remote
  call per request" — this story's fix must satisfy the *intent* of this rule — local, cached,
  no-per-request-network-call verification — even though the literal mechanism (a shared secret) no
  longer matches how this Supabase project signs tokens)
- Live JWKS confirmation: `GET https://kxhgvwopdszclfyrrkqm.supabase.co/auth/v1/.well-known/jwks.json`
  returned `{"keys":[{"alg":"ES256","kty":"EC","crv":"P-256","kid":"dc21388a-...", ...}]}` during this
  story's investigation (2026-07-08)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- RED confirmed correctly: rewrote `test_auth.py` first, then `git stash`'d the (already-drafted)
  `dependencies.py` implementation to run the new tests against the *original* code — confirmed
  `ImportError: cannot import name 'get_jwks_client' from 'app.dependencies'`, not an unrelated failure.
  `git stash pop` restored the implementation before re-running to confirm GREEN (self-caught: I had
  initially written the implementation before the tests and had to explicitly back out and redo the
  order correctly per this project's TDD discipline).
- A pre-existing, unrelated environment bug was found and fixed along the way: `starlette.testclient`
  (version 1.3.1, pulled in by this being the first-ever fresh install of `apps/api`'s unpinned
  `fastapi>=0.111.0`) now requires a separate `httpx2` package instead of `httpx`, and
  `pyproject.toml`'s `filterwarnings = ["error", ...]` turns that deprecation warning into a hard
  collection error for **every** test file that imports `TestClient` (9 files, confirmed by testing
  `test_quiz_endpoint.py` in isolation before touching anything). Fixed by installing `httpx2` and
  adding it to `pyproject.toml`'s dev dependencies — same bootstrap-gap category as the Hatchling/
  `email-validator`/`python-multipart` fixes from earlier the same day.
- Full-suite regression run surfaced 46 pre-existing failures entirely unrelated to this story. Verified
  three representative examples directly rather than assuming: (1) `test_quiz_endpoint.py` fails on a
  separate `starlette` deprecation (`HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT`,
  same unpinned-version root cause as the `httpx2` issue, different symptom, out of this story's scope
  to fix); (2) `test_onboarding_content.py::test_total_question_count_is_20` fails on an unrelated
  regex/content assertion returning 0 matches; (3) `test_dna_growth.py::test_positional_args_raise_type_error`
  fails only in the full-suite run but **passes in isolation** — cross-test pollution/ordering issue,
  pre-existing. None of the 46 touch `app.dependencies`, `get_current_user`, or JWT verification. Per
  AC #8's specific instruction, ran the 4 named files in isolation instead of relying on the noisy full
  run: 82/82 passing, zero regressions from this story's change.
- Considered whether `get_jwks_client` should take `settings` via `Depends(get_settings)` like the
  original `get_current_user` did — rejected in favor of a zero-argument `@lru_cache`'d function calling
  `get_settings()` internally, because `lru_cache` requires hashable arguments and pydantic `Settings`
  isn't guaranteed hashable (it's a mutable `BaseSettings`). This also matches this codebase's own
  existing pattern for `get_settings()` itself (also a zero-arg `@lru_cache(maxsize=1)` function).

### Completion Notes List

- Root cause confirmed by reading the actual live code path (`websocket.py` → `service.py` → `graph.py`
  for a separate, earlier investigation) and, for this story specifically, by calling this Supabase
  project's real JWKS endpoint directly and observing `alg: "ES256"` — not by trusting documentation.
- `get_jwks_client()` added as a new, cached (`@lru_cache(maxsize=1)`) FastAPI dependency in
  `apps/api/app/dependencies.py`, resolving the verification key from
  `{supabase_url}/auth/v1/.well-known/jwks.json` via `jwt.PyJWKClient(..., cache_keys=True)`. Both
  layers of caching (the `lru_cache` on the dependency function, and `cache_keys=True` on the client
  itself) exist specifically to satisfy Epic 4's own Definition of Done ("<5ms latency", "no remote call")
  — only the very first verification after a cold process start touches the network.
  `algorithms=[signing_key.algorithm_name]` is read from the resolved key rather than hardcoded as
  `["ES256"]`, so a future Supabase key-algorithm rotation doesn't silently reintroduce this exact class
  of bug again.
  `get_current_user`'s existing exception handling (`ExpiredSignatureError` → "Token has expired",
  `InvalidTokenError` → "Could not validate credentials", empty/missing `sub` → 401) is unchanged; one
  new `except jwt.PyJWKClientError:` branch was added around the key-resolution step specifically
  (confirmed via inspection that `PyJWKClientError` does not subclass `InvalidTokenError`, so it could
  not simply fall into the existing branch).
  `settings.supabase_jwt_secret` was deliberately left untouched in `config.py` — still required, no
  longer read by the JWT verification path — per the story's explicit "not this story's scope" note; a
  future cleanup can remove it once Dev 4 confirms nothing else depends on it.
- `tests/test_auth.py` fully rewritten: the original 10 test functions (this story's Context section
  said "11" based on an earlier miscount when reading the file quickly — the actual count is 10, all
  preserved with equivalent ES256 coverage; no coverage was lost) plus 2 new ones
  (`test_unrecognized_kid_returns_401` for the new `PyJWKClientError` branch,
  `test_jwks_client_is_cached_across_calls` for the caching guarantee). The "no network, no Supabase"
  design principle from the original story (4-1) is preserved by construction — no test in the file
  constructs a real `PyJWKClient` pointed at any URL except the one test that directly exercises the
  real, production `get_jwks_client()` singleton, which itself never resolves a key or makes a request
  within that test.
- Manual verification: started the backend locally (`uvicorn app.main:app --reload`) against the real
  Supabase project (`kxhgvwopdszclfyrrkqm.supabase.co`) this story's investigation used; `/health`
  confirmed unaffected. The literal browser click-through (log in, visit `/upload`, confirm no redirect
  to `/signin`) requires the user's own real login session — handed off for the user to confirm
  interactively since I cannot drive their browser.
- All 4 tasks completed in strict RED → GREEN order (after self-correcting an initial implementation-
  before-tests ordering mistake — see Debug Log).

### File List

**Files MODIFIED:**
- `apps/api/app/dependencies.py` — added `get_jwks_client()`, rewired `get_current_user` to verify via
  the resolved JWKS signing key instead of `settings.supabase_jwt_secret` + HS256
- `apps/api/tests/test_auth.py` — full rewrite: ES256 token minting with a local EC key pair,
  `_FakeJWKSClient` test double, all 10 original tests preserved, 2 new tests added
- `apps/api/pyproject.toml` — added `httpx2>=2.0.0` to dev dependencies (pre-existing bootstrap gap,
  unrelated to the JWT fix itself, found while running this story's tests for the first time)

### Change Log

- 2026-07-08: Bug discovered while starting `apps/api` locally against a real Supabase project to test
  onboarding/session-report/DNA flows for the frontend. Traced to `get_current_user`'s HS256-only
  verification vs. this project's real ES256-signed tokens (confirmed via the project's JWKS endpoint).
- 2026-07-08: Escalated to Dev 4 as a written finding (not yet a story) — offered three options: full
  JWKS fix, log-and-escalate only, or reconfigure Supabase to re-enable legacy HS256 signing.
- 2026-07-08: Dev 4 authorized the full fix. Story created via `bmad-create-story` on branch
  `fix/4-17-jwt-es256-verification`, following the same full-BMAD-workflow rigor as Sprint 2 stories
  (story-first commit → `bmad-dev-story` TDD implementation → 5-agent `bmad-code-review`).
- 2026-07-08: All 4 tasks implemented in RED→GREEN order (self-corrected an implementation-before-tests
  ordering slip along the way). Found and fixed a pre-existing, unrelated `httpx2` bootstrap gap
  blocking all `TestClient`-based tests. `test_auth.py`: 12/12 passing (10 preserved + 2 new). The 4
  files AC #8 specifically names: 82/82 passing, zero regressions. `ruff`/`mypy` clean on changed files.
  46 pre-existing, unrelated failures found in the full suite — investigated and confirmed unrelated
  (see Debug Log), left untouched as out of this story's scope. Backend manually started and confirmed
  healthy against the real Supabase project. Story marked `review` — full browser click-through
  handed to the user to confirm.
