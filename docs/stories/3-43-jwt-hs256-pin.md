# Story 3-43: JWT HS256 Algorithm Pin for WebSocket/API Auth (D80)

## Story

**As a** system,  
**I want** JWT verification to default to HS256 and reject non-HS256 tokens unless JWKS fallback is explicitly enabled via config,  
**so that** an attacker cannot force a JWKS fetch or algorithm-confusion attack by forging the `alg` header of an unverified token.

## Context

**Defect:** D80 — `dependencies.py:get_current_user` reads `jwt.get_unverified_header(token).get("alg")` to branch between HS256 local verification and JWKS remote verification. Because the `alg` field is in the **unverified** part of the JWT, an attacker can set `alg=RS256` (or any non-HS256 algorithm) to:
- Force a remote JWKS fetch on every forged request (DoS amplification)
- Trigger algorithm confusion if the server can be tricked into verifying an HS256-signed token using a public key (OWASP JWT attack)

**CLAUDE.md constraint:** "JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) — never remote call per request". The current code violates this for any token with a forged non-HS256 alg header.

**Approved fix:** Pin to HS256 by default. JWKS fallback only if `settings.ws_allow_jwks_fallback=True` (default False). Reject any non-HS256 token unless the flag is enabled.

**Standard Supabase setup uses HS256** — the JWKS path is not needed for the standard deployment. The fallback exists for future-proofing (asymmetric key rotation); it is disabled by default as of this story.

## Acceptance Criteria

### AC1 — Config flag added
`settings.ws_allow_jwks_fallback: bool = False` in `config.py`, sourced from env var `WS_ALLOW_JWKS_FALLBACK`.

### AC2 — Default path: HS256 only, no unverified header read
When `ws_allow_jwks_fallback=False` (the default), `get_current_user` in `dependencies.py`:
- Does NOT read `jwt.get_unverified_header(token)` to decide the verification path
- Always uses `jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], ...)`
- Returns 401 if the token was NOT signed with HS256 (the `algorithms=["HS256"]` constraint causes PyJWT to raise `InvalidAlgorithmError` on non-HS256 tokens)

### AC3 — Non-HS256 token rejected with 401 (default config)
A token with `alg=RS256` or `alg=none` in the header is rejected with 401 when `ws_allow_jwks_fallback=False`. No JWKS fetch occurs.

### AC4 — JWKS fallback works when explicitly enabled
When `ws_allow_jwks_fallback=True`, the existing JWKS branch is preserved (tokens with `alg=ES256` or `alg=RS256` are verified via JWKS). The behavior for this flag=True case must remain backward-compatible with the current implementation.

### AC5 — HS256 token with valid secret still accepted (no regression)
A valid HS256 token signed with `settings.supabase_jwt_secret` is accepted in both `ws_allow_jwks_fallback=False` (default) and `ws_allow_jwks_fallback=True` cases.

### AC6 — Algorithm confusion attack impossible (default config)
A forged RS256 token cannot trigger a JWKS fetch when `ws_allow_jwks_fallback=False`. PyJWT raises `InvalidAlgorithmError` before any remote call.

### AC7 — DEFECT-REGISTER.md updated
D80 status updated to `FIXED` with story reference `S3-43` and the guard (`test_jwt_hs256_pin_rejects_non_hs256_by_default` in CI).

## Scale & Load

1. **Unit of work and range:** One JWT verification per HTTP request. Range: 1–∞ requests/s (Sprint 3: very low; production: bounded by Railway instance limit).
2. **Fixed budget while input varies:** `supabase_jwt_secret` is fixed per deployment. HS256 verification is O(1) CPU + 0 network. No budget concerns.
3. **Scope of limit:** Per-deployment (all instances use the same `ws_allow_jwks_fallback` flag). Changing requires env var update + restart.
4. **Unbounded reads/writes:** None — verification is in-memory. The JWKS path (when enabled) does a remote fetch, but that's unchanged behavior behind an explicit flag.
5. **Inherited caps re-derived:** The JWKS client was added with `cache_keys=True`. If `ws_allow_jwks_fallback=True`, the cache means keys are only fetched on rotation — this is unchanged. The cap on concurrent JWKS fetches is inherited from `PyJWKClient` (single global instance). Acceptable.
6. **Check-then-act safety:** No check-then-act. Verification is atomic and stateless.

## Dev Notes

- File to change: `apps/api/app/dependencies.py` (get_current_user) and `apps/api/app/config.py` (add flag)
- The current `get_current_user` (lines 50–108) reads `unverified_header` and branches. New version: skip `get_unverified_header` when `ws_allow_jwks_fallback=False`; read it only when the flag is True
- Do NOT change the exception types raised (HTTPException 401) — they're part of the frozen API contract
- The `_get_jwks_client` helper and `_jwks_client` global can remain unchanged
- Test approach: mock `jwt.decode` and `jwt.get_unverified_header`; verify `get_unverified_header` is NOT called when flag=False; verify 401 on non-HS256 token
- Guard: `test_jwt_hs256_pin_rejects_non_hs256_by_default` — must verify `jwt.get_unverified_header` is never called when flag=False

## BMAD Process Gate

- [ ] Story file committed first
- [ ] Story commit pushed to `sprint3/s3-43-ws-jwt-hs256-pin` before any implementation
- [ ] RED tests written and failing
- [ ] GREEN implementation passes
- [ ] REFACTOR (no logic changes)
- [ ] DEFECT-REGISTER.md D80 updated to FIXED + guard name

## Status

Draft
