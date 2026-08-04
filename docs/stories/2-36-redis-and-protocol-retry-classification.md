# Story 2.36: A Redis blip must not be a pipeline outage (D19, D20)

Status: ready-for-dev

## Story

As a student whose lesson is being generated,
I want a momentary Redis hiccup or a connection dropped mid-response to be retried like any
other transient failure,
so that a two-second infrastructure blip does not kill a 5–15 minute generation job that has
already been paid for in LLM spend.

**Source:** `docs/DEFECT-REGISTER.md` **D19** and **D20**. Both listed OPEN — live in production.

## The defects

Both are the same shape as D3, which is why they survived it: `with_retry` classifies by
exception type, and the classification was written against a mental model of the libraries
rather than against the libraries.

### D19 — every redis exception is fatal

```python
# app/core/retry.py:183
except (httpx.TimeoutException, httpx.NetworkError, TimeoutError) as exc:
    last_exc = exc
```

`TimeoutError` there is the **builtin**. Verified by execution:

```
redis.TimeoutError is builtins.TimeoutError            -> False
issubclass(redis.TimeoutError, builtins.TimeoutError)  -> False
redis.TimeoutError MRO      -> TimeoutError, RedisError, Exception, BaseException, object
redis.ConnectionError MRO   -> ConnectionError, RedisError, Exception, BaseException, object
issubclass(redis.ConnectionError, builtins.ConnectionError) -> False
```

`redis.exceptions` defines its **own** `TimeoutError` and `ConnectionError` that shadow the
builtins by name and inherit from `RedisError`, not from them. So both fall through every
branch to `except Exception` — logged at ERROR with a traceback, and **re-raised without a
single retry.**

**Why that reaches production:** `is_circuit_open()` is called *inside* every function wrapped
by `@with_retry` — e.g. `providers/llm/openai.py:111`, and the same line in
`providers/embeddings/openai.py`, `providers/image/imagen.py`, `providers/image/openai_image.py`.
It talks to Redis. So the first statement of every retried provider call is a Redis round-trip
whose failure is classified as an unknown bug.

**A Redis blip therefore fails the node before the provider is ever called** — and, because
`with_retry` doesn't retry it, fails it permanently. `guard_breaker`'s docstring states the
opposite intent: *"Bookkeeping is best-effort. A Redis outage must never convert an
already-paid-for provider result into an exception."* That promise is kept for `_safe_record`
(which catches broadly) and silently broken for `is_circuit_open`.

### D20 — a server closing the connection mid-response is fatal

Verified by execution:

| httpx exception | `NetworkError` | `TimeoutException` | `TransportError` |
|---|---|---|---|
| `ReadError`, `WriteError`, `ConnectError`, `CloseError` | **yes** | no | yes |
| `ReadTimeout`, `ConnectTimeout`, `WriteTimeout`, `PoolTimeout` | no | **yes** | yes |
| **`RemoteProtocolError`** | **no** | **no** | yes |
| `LocalProtocolError` | no | no | yes |
| `ProxyError`, `UnsupportedProtocol` | no | no | yes |

`RemoteProtocolError` is neither, so it falls to `except Exception` and is never retried. It is
raised when the **server** violates the protocol or closes the connection mid-response — routine
and transient behaviour from a loaded provider, and precisely what retry exists for.

## Acceptance Criteria

1. **AC-1 — `is_circuit_open()` fails OPEN.** When the Redis call inside it raises, it returns
   `False` (allow the call through) and logs a WARNING. A breaker whose state cannot be read
   must not block traffic: refusing every provider call because bookkeeping is unavailable
   converts a Redis blip into a total outage, which is strictly worse than the stale-state risk
   it would be avoiding. This mirrors `_safe_record`, which already fails open.
2. **AC-2 — redis exceptions are retryable in `with_retry`.** `redis.exceptions.TimeoutError`
   and `redis.exceptions.ConnectionError` (which covers `BusyLoadingError`, a subclass) are
   classified transient, exactly like `httpx.TimeoutException`. A test must assert the call is
   **re-attempted and then succeeds**, not merely that no exception escaped.
3. **AC-3 — the premise is pinned by an executable assertion.** A test must assert
   `redis.exceptions.TimeoutError is not TimeoutError` **and** that it is not a subclass of the
   builtin. Per CLAUDE.md binding rule 3: the reason D3, D19 and D20 all shipped is that the
   `except` clause encoded an unverified belief about a third-party type hierarchy. If a future
   redis release makes these aliases of the builtins, this test fails and tells us the branch is
   now redundant — rather than the branch silently becoming dead code.
4. **AC-4 — `httpx.RemoteProtocolError` is retried.** Asserted by re-attempt-then-succeed, not
   by inspecting a tuple.
5. **AC-5 — `httpx.LocalProtocolError` is NOT retried.** This is the load-bearing half. Both are
   `ProtocolError` subclasses, so the tempting fix — catching `httpx.ProtocolError` — would also
   retry **our own malformed requests** three times. `LocalProtocolError` means *this process
   built a bad request*; it is a code defect and cannot succeed on attempt two. The same applies
   to `UnsupportedProtocol` (a bad URL scheme in config). A test must assert exactly one attempt
   for `LocalProtocolError`.
6. **AC-6 — a Redis outage does not open the circuit breaker.** `_is_client_error` returns
   `False` for a redis error, so `guard_breaker` currently counts it as a **provider** failure.
   Five Redis blips in 120s would open the breaker for a provider that is perfectly healthy and
   was never contacted, causing a 600-second outage. The breaker must record failures only for
   errors that were actually raised by the provider.
7. **AC-7 — no regression.** Full suite shows exactly the pre-existing failures. `ruff check`,
   `ruff format --check` and `mypy app` produce no findings not already at baseline, measured
   **repo-wide** (CLAUDE.md binding rule 1).

## Tasks / Subtasks

- [ ] Task 1 (AC-3): premise tests first — pin the redis and httpx type hierarchies. These fail
      against nothing; they are the executable statement of what the fix assumes.
- [ ] Task 2 (AC-1): `is_circuit_open` fails open on a Redis error.
- [ ] Task 3 (AC-2, AC-4, AC-5): retry classification for redis errors and `RemoteProtocolError`;
      `LocalProtocolError` explicitly excluded.
- [ ] Task 4 (AC-6): `guard_breaker` must not count an infrastructure error as a provider failure.
- [ ] Task 5 (AC-7): full suite, lint, types.

## Dev Notes

- **Do NOT catch `httpx.TransportError`.** It is the common ancestor of all of them, including
  `LocalProtocolError` and `UnsupportedProtocol`. Widening to the base class is how a fix for
  D20 would quietly introduce three-attempt retries on our own bugs. Name `RemoteProtocolError`
  explicitly — see AC-5.
- **Do NOT catch `httpx.ProxyError` in this story.** It is plausibly transient, but a
  misconfigured proxy raises it too, and no defect report covers it. Deliberately out of scope;
  add it when there is evidence, not on the strength of it seeming reasonable. Recording this
  because "seemed reasonable" is how `_NON_RETRYABLE_STATUS_CODES` drifted.
- **Use the `_exception_classes()` guard for the redis import**, exactly as the openai import
  does. `redis` is a hard dependency (`pyproject.toml`), so an ImportError is not expected — but
  parts of the suite install module stubs via `sys.modules.setdefault`, whose attributes are
  Mocks, and `except <Mock>` raises `TypeError: catching classes that do not inherit from
  BaseException`. That exact failure already happened once on this codebase (D3's first fix).
- **Redis failure ≠ provider failure, anywhere.** AC-1 and AC-6 are the same principle applied
  at two layers: our inability to reach our own bookkeeping store says nothing about OpenAI's
  health, and must never be recorded or acted upon as if it did.
- Every new test needs `@pytest.mark.unit` (and `asyncio` where async).

### Explicitly OUT of scope

- `httpx.ProxyError` / `UnsupportedProtocol` classification (see Dev Notes).
- Any change to `FAILURE_THRESHOLD`, `FAILURE_WINDOW_SECONDS` or `RECOVERY_TIMEOUT_SECONDS`.
- Retrying the Redis buffer or WebSocket paths — Dev 4's modules.

### Project Structure Notes

Touches `apps/api/app/core/retry.py`, `apps/api/app/core/circuit_breaker.py` and tests. **No**
`packages/shared/*`, **no** `supabase/migrations/*` — §16 gate not triggered. Zero `apps/web/**`.

### Branching

`sprint2/dev1-d19-d20-retry-classification`, based on `main`.

### References

- [Source: docs/DEFECT-REGISTER.md — D19, D20; D3 for the identical root cause]
- [Source: CLAUDE.md §14 failure modes; binding rules 1 and 3]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Story created for D19 + D20. Both premises verified by execution before the ACs were written. | Dev 1 |
