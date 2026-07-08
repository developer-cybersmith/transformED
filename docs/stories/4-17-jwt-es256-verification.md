---
baseline_commit: "80dccc5a071bbdd14c7baa9de520cab72f208d6f"
---

# Story 4-17: JWT Verification Must Support ES256 (JWKS), Not Just HS256

Status: done

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
    from this story's investigation; `/health` unaffected. Post-review-patch, also confirmed
    `GET /api/tutor/session/sess-001/state` with a garbage bearer token against the REAL, live JWKS
    endpoint (not mocked) returns 401 with no server-side exception — the first time this story's fix
    has been exercised against the real Supabase project over the network, not just unit tests. This
    does not fully satisfy AC #9 on its own (no genuinely valid Supabase-issued token was used, since
    that requires the user's own login session) — full browser click-through (`/upload` no longer
    redirecting to `/signin`) still handed to the user to confirm interactively, now with materially
    higher confidence since the `aud`-validation bug that would have made that check fail is fixed.

### Review Findings

5-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run against branch `fix/4-17-jwt-es256-verification` vs `main`, 2026-07-08. Two findings independently confirmed by direct testing/source-reading against the installed `PyJWT` package before triage, not just taken on the reviewers' word.

- [x] [Review][Patch] **`aud` claim never validated — real Supabase tokens will still 401, reproducing the exact bug this story exists to fix.** `jwt.decode()` is called with no `audience=` kwarg; PyJWT's `verify_aud` defaults to requiring one whenever the payload carries a non-empty `aud` claim, and Supabase GoTrue tokens always carry `"aud": "authenticated"`. Confirmed by direct test: minting an ES256 token with `aud: "authenticated"` and decoding without an `audience` kwarg raises `InvalidAudienceError` — caught by the generic `except jwt.InvalidTokenError` → silent 401. `test_auth.py`'s token helper never includes an `aud` claim, so this path was never exercised by any test. [apps/api/app/dependencies.py] — fixed: added `audience="authenticated"` to the `jwt.decode()` call with a comment explaining why it's hardcoded (a stable Supabase-platform-wide convention, not project-specific config); `_token()`'s default claims now include `aud: "authenticated"` so every existing test implicitly re-guards the regression, plus a new dedicated `test_wrong_audience_returns_401`
- [x] [Review][Patch] **Exception handling around `get_signing_key_from_jwt()` misses sibling exceptions and escapes as uncaught 500s.** Only `jwt.PyJWKClientError` is caught. Confirmed by reading the installed `jwt/exceptions.py` and `jwt/jwks_client.py` directly: a malformed token raises `jwt.DecodeError` (sibling of `PyJWKClientError`, not a subclass — confirmed by direct test), an empty/malformed JWKS `keys` array raises `jwt.PyJWKSetError` (also a sibling), and a non-JSON JWKS response raises `json.JSONDecodeError` (not a PyJWT exception at all — `fetch_data()`'s own `except (URLError, TimeoutError)` doesn't cover it). All three currently propagate as unhandled 500s instead of the intended 401. [apps/api/app/dependencies.py] — fixed: broadened to `except (jwt.PyJWTError, ValueError):` around the key-resolution step (catches all PyJWT exception types plus `JSONDecodeError`, a `ValueError` subclass); added 3 new tests using a REAL `PyJWKClient` (fetch_data monkeypatched, never the network layer) exercising each of the three real exception types through `get_current_user`
- [x] [Review][Patch] **Blocking synchronous network I/O runs directly inside `async def get_current_user`, stalling the entire event loop.** `jwks_client.get_signing_key_from_jwt(token)` internally calls `urllib.request.urlopen(..., timeout=30)` synchronously — not dispatched via `asyncio.to_thread`/`run_in_threadpool`. A slow or unresponsive JWKS endpoint blocks every other concurrent request on that worker for up to 30s, not just the one that missed cache. [apps/api/app/dependencies.py] — fixed: wrapped in `await asyncio.to_thread(jwks_client.get_signing_key_from_jwt, token)`; added `test_jwks_lookup_runs_off_the_event_loop_thread`, which detects via `asyncio.get_running_loop()` raising `RuntimeError` inside the dispatched call that it's genuinely running off the event loop thread
- [x] [Review][Patch] **AC9's manual verification only checked `/health` (unauthenticated) — no real `CurrentUser`-protected endpoint was ever exercised with a real bearer token.** The completion notes overstate what was verified, and per the `aud`-claim finding above, an actual attempt against a real endpoint would have failed. Re-verify for real once the `aud` fix lands, and correct the story's own completion notes to reflect what was actually checked. [docs/stories/4-17-jwt-es256-verification.md, apps/api/app/dependencies.py] — addressed: re-verified against the REAL, live Supabase JWKS endpoint (not mocked) post-patch — `GET /api/tutor/session/sess-001/state` with a garbage bearer token now correctly returns 401 with no server exception, the first time this fix has run against the real project over the network. Task 4.3 and this entry corrected to state precisely what was and wasn't verified; genuine browser click-through with a real login session still needs the user, now with materially higher confidence
- [x] [Review][Patch] **`test_jwks_client_is_cached_across_calls` doesn't prove AC4's actual requirement.** AC4 asks for a test proving no repeated key-fetch across two verifications sharing a `kid`; the implemented test only proves the `@lru_cache`'d wrapper function returns the same `PyJWKClient` object by identity — it never exercises a real fetch-count against the underlying client. Strengthen with a test that mocks `PyJWKClient.fetch_data` (or equivalent) with a call counter and asserts it's invoked at most once across two `get_signing_key_from_jwt` calls sharing a `kid`. [apps/api/tests/test_auth.py] — fixed: added `test_real_pyjwkclient_caches_key_fetch_across_two_lookups`, which builds a real JWK dict from the test EC public key, monkeypatches `fetch_data` with a call counter, and asserts exactly one fetch across two lookups sharing a `kid` — the original identity-based test is kept alongside it, not replaced
- [x] [Review][Patch] **AC6's requested "no real network" assertion-based guard was skipped in favor of a design argument.** The Dev Agent Record explicitly documents substituting "satisfied by construction" for the literal ask. Add a lightweight guard (e.g. monkeypatch `urllib.request.urlopen` at the start of the module/via an autouse fixture to raise if ever called) proving no test in the file can accidentally make a real HTTP call. [apps/api/tests/test_auth.py] — fixed: added an autouse `_forbid_real_network_calls` fixture that monkeypatches `urllib.request.urlopen` to raise `AssertionError` if ever called, active for every test in the file
- [x] [Review][Patch] **`cryptography` (required for ES256) is only present as a transitive dependency, not declared explicitly.** Verified present via `pip show cryptography` (49.0.0, pulled in transitively via `pdfminer.six`), but `apps/api/pyproject.toml`'s runtime `dependencies` list has no direct reference to it or `pyjwt[crypto]`. ES256 verification is now load-bearing production functionality, not a dev-only nicety — a future change elsewhere in the dependency tree could silently remove it. [apps/api/pyproject.toml] — fixed: added `"cryptography>=42.0.0"` to the main `dependencies` list with a comment explaining why
- [x] [Review][Patch] **Unguarded URL construction — a trailing slash in `supabase_url` produces a malformed double-slash JWKS URL.** `f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"` has no `.rstrip("/")` safeguard, and nothing tests this construction. [apps/api/app/dependencies.py] — fixed: added `.rstrip("/")` on `settings.supabase_url` before building the URL; added `test_jwks_url_strips_trailing_slash_from_supabase_url`
- [x] [Review][Patch] **AC8's checkbox/notes overstate "full suite passes."** 46 pre-existing, unrelated failures exist in the full suite (confirmed unrelated via direct investigation of 3 representative examples). The AC's literal text doesn't carve out an exception for pre-existing failures. Correct the story's own wording to precisely state what was verified (full suite run; failures found and confirmed pre-existing/unrelated; the 4 AC-named files pass in isolation, 82/82) rather than implying a clean full-suite pass. [docs/stories/4-17-jwt-es256-verification.md] — fixed: Task 4.1's wording already scoped its claim to "the 4 files this AC specifically names... 82/82 passing" rather than claiming the full suite passes; no further code or text change needed beyond this review-findings entry itself making the resolution explicit
- [x] [Review][Defer] No negative-caching for an unrecognized `kid` — `PyJWKClient.get_signing_key()`'s retry-with-refresh path forces a real network fetch on every request carrying a `kid` that never matches any published key, bypassing the Tier-1 300s cache entirely (confirmed by reading `jwks_client.py`'s `get_signing_key` source). A genuine DoS/latency vector under a flood of garbage tokens, and a real gap in the "no remote call per request" claim for that class of input. [apps/api/app/dependencies.py] — deferred, needs a rate-limiting or negative-cache design decision bigger than this story's scope; the story's own AC4 only asked for the happy-path (matching-kid) caching guarantee, which is met
- [x] [Review][Defer] Per-`kid` signing-key cache (Tier 2, `cache_keys=True`) has no time-based expiration — only LRU eviction — confirmed via the installed `PyJWKClient`'s own docstring. A rotated/compromised key stays trusted for the life of the process with no forced-refresh path short of a restart. [apps/api/app/dependencies.py] — deferred, this is an inherent trade-off of the `cache_keys=True` design this story's own AC1/AC4 mandated, not a new bug introduced by the implementation; worth documenting as a known limitation for Dev 4
- [x] [Review][Defer] `test_jwks_client_is_cached_across_calls` manipulates the real, process-wide `get_jwks_client` singleton's cache directly (`cache_clear()`) rather than an isolated fake. [apps/api/tests/test_auth.py] — deferred, currently safe (guarded by try/finally, every other test uses dependency-override fakes that never touch the real singleton); a broader autouse reset fixture would be more robust but isn't blocking since no actual cross-test pollution has occurred

**Dismissed as noise/false-positive (6):** "Algorithm confusion" from reading the algorithm off `signing_key.algorithm_name` instead of a hardcoded `["ES256"]` — this is the explicit, spec-mandated design (AC2, "What NOT to do") and isn't actually vulnerable, since the algorithm comes from the trusted JWKS response (fetched over HTTPS from the real Supabase project), not from attacker-controlled token input; the classic RS256-vs-HS256 confusion attack this pattern normally guards against doesn't apply here. "No cache expiry configured" for the JWK-set cache — factually incorrect, contradicted by `PyJWKClient`'s own default `lifespan=300` (5 minutes), confirmed by reading its `__init__` signature and docstring directly; the reviewer that raised this lacked access to check the actual default. `httpx2` flagged as a suspicious/fabricated dependency by two reviewers — verified genuine by directly installing it from PyPI and confirming Starlette's own `testclient.py` explicitly names it as the required replacement package. `settings.supabase_jwt_secret` left unused in `config.py` — explicitly out of scope per AC5 and "What NOT to do." Vestigial `get_settings` dependency override left in the test app even though `get_current_user` no longer reads it — intentional and documented (kept in case another route on the same test app reads it), harmless. Duplicated test boilerplate in `test_unrecognized_kid_returns_401` (a fresh `FastAPI()` app instead of reusing `_app`) — minor DRY style preference, not a correctness issue.

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
- Review-patch pass (2026-07-08): two of the 9 patch findings (`aud` validation, exception-hierarchy
  gaps) were independently re-verified by direct testing/source-reading before triage even began — not
  taken on the reviewers' word. `jwt.decode()` without an `audience` kwarg against a token minted with
  `aud: "authenticated"` was confirmed to raise `InvalidAudienceError` via a standalone script before
  touching any code. The exception hierarchy (`DecodeError`/`PyJWKSetError` as *siblings* of, not
  subclasses of, `PyJWKClientError`, all three under the common `PyJWTError` base) was confirmed by
  reading the installed `jwt/exceptions.py` and `jwt/jwks_client.py`/`jwt/api_jwk.py` source directly,
  not assumed from the review agent's report.
- RED confirmed for the patch round the same way as the initial implementation: rewrote
  `apps/api/tests/test_auth.py` first (all patch fixes' tests), ran against the pre-patch
  `dependencies.py`, confirmed 6 failures for the expected reasons (401 instead of 200 on
  `test_valid_token_returns_200` once `aud` was added to the default token claims — proving the
  regression was real and broad, not confined to one new test; 500s on the three new real-`PyJWKClient`
  exception tests; wrong URL on the trailing-slash test), then applied the `dependencies.py` and
  `pyproject.toml` fixes and confirmed all 19 tests GREEN.
- `test_wrong_audience_returns_401` technically passed even before the `audience=` fix landed — but for
  the *wrong* reason (any token with a non-empty `aud` and no `audience` kwarg on decode was already
  raising `InvalidAudienceError` regardless of the `aud` value's content, so a "wrong audience" and a
  "correct audience" token were indistinguishable pre-fix). Confirmed via the RED run above that
  `test_valid_token_returns_200` (an unambiguous positive-path signal) failed correctly, which is what
  actually proves the bug and its fix — noted here so a coincidentally-passing assertion isn't mistaken
  for a meaningful RED signal on its own, matching a lesson from this session's earlier Sprint 2 work.

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
- Applied all 9 `[Review][Patch]` findings from the 5-agent code review (Blind Hunter, Edge Case Hunter,
  Acceptance Auditor): added `audience="authenticated"` to `jwt.decode()` (the critical fix — without
  it, real Supabase tokens still 401'd, meaning the pre-patch code didn't actually solve the story's
  own stated problem); broadened exception handling around the JWKS key-resolution step from
  `except jwt.PyJWKClientError` to `except (jwt.PyJWTError, ValueError)` to also catch `DecodeError`,
  `PyJWKSetError`, and `json.JSONDecodeError`; dispatched the blocking `get_signing_key_from_jwt` call
  via `asyncio.to_thread` so a slow JWKS endpoint can't stall the whole event loop; added `.rstrip("/")`
  on `supabase_url`; declared `cryptography` as an explicit runtime dependency; added an autouse
  no-real-network guard fixture; strengthened the AC4 caching test with a real fetch-count assertion;
  and corrected the story's own AC9 completion notes to state precisely what was and wasn't verified.
  7 new tests added (`test_wrong_audience_returns_401`, `test_malformed_token_via_real_client_returns_401`,
  `test_empty_jwks_response_returns_401`, `test_jwks_endpoint_non_json_response_returns_401`,
  `test_jwks_lookup_runs_off_the_event_loop_thread`, `test_real_pyjwkclient_caches_key_fetch_across_two_lookups`,
  `test_jwks_url_strips_trailing_slash_from_supabase_url`), bringing `test_auth.py` to 19 tests, all
  GREEN. The 3 deferred findings were explicitly deferred (see Review Findings above and
  `_bmad-output/implementation-artifacts/deferred-work.md`) as out of this story's scope; 6 dismissed
  as noise/false-positives (two of which — the algorithm-source concern and the cache-TTL claim — were
  independently verified as spec-intentional or factually incorrect before dismissing, not just waved
  off).

### File List

**Files MODIFIED:**
- `apps/api/app/dependencies.py` — added `get_jwks_client()`, rewired `get_current_user` to verify via
  the resolved JWKS signing key instead of `settings.supabase_jwt_secret` + HS256; review-patch pass
  added `audience="authenticated"`, broadened exception handling (`except (jwt.PyJWTError, ValueError)`),
  `asyncio.to_thread` dispatch for the key-resolution call, `.rstrip("/")` on `supabase_url`
- `apps/api/tests/test_auth.py` — full rewrite: ES256 token minting with a local EC key pair,
  `_FakeJWKSClient` test double, all 10 original tests preserved, 2 new tests added; review-patch pass
  added 7 more tests (19 total) plus an autouse no-real-network guard fixture and a `_jwk_dict_for`
  helper for building real JWK payloads
- `apps/api/pyproject.toml` — added `httpx2>=2.0.0` to dev dependencies (pre-existing bootstrap gap,
  unrelated to the JWT fix itself, found while running this story's tests for the first time);
  review-patch pass added `cryptography>=42.0.0` to the main runtime dependencies

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
- 2026-07-08: 5-agent adversarial review run (Blind Hunter, Edge Case Hunter, Acceptance Auditor); 9
  patch findings, 3 deferred, 6 dismissed as noise. Two of the patch findings (`aud` validation gap,
  exception-hierarchy gaps) independently confirmed by direct testing and source-reading before triage —
  the pre-patch implementation did not actually fix the story's own stated symptom for real Supabase
  tokens.
- 2026-07-08: All 9 patch findings applied in RED→GREEN order; 7 new tests (`test_auth.py` now 19
  tests, all GREEN); the 4 files AC #8 names re-run alongside `test_auth.py`: 101/101 passing;
  `ruff`/`mypy` clean. Backend restarted and, for the first time, exercised against the REAL live
  Supabase JWKS endpoint (not mocked) with a malformed token — confirmed 401, no server exception.
  Story marked `done`.
