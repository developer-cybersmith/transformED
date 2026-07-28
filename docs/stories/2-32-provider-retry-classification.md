# Story 2.32: Provider retry exception classification + circuit-breaker accounting

Status: ready-for-dev

## Story

As Dev 1 (provider abstraction owner),
I want `with_retry` to actually classify the exceptions our providers really raise, and the circuit breaker to count **logical calls** rather than individual retry attempts,
so that a transient OpenAI rate-limit is retried per PRD §14 instead of failing the pipeline outright — without the fix turning a 30-second blip into a 10-minute provider outage.

**Source:** Bug C from `DEV1-FIX-PLAN.md`, Branch 3.

## Context: two distinct defects, one shared trap

### Defect 1 — OpenAI SDK exceptions are never retried

`app/core/retry.py:with_retry` classifies only `httpx.HTTPStatusError`,
`httpx.TimeoutException`, `httpx.NetworkError` and `TimeoutError`. Everything else
falls into `except Exception: logger.exception(...); raise` — no retry.

**Verified by introspection against the installed SDK** (not assumed):

```
APIError              httpx-derived=False   mro=[APIError, OpenAIError, Exception, ...]
APIStatusError        httpx-derived=False
APIConnectionError    httpx-derived=False
APITimeoutError       httpx-derived=False   mro=[APITimeoutError, APIConnectionError, APIError, ...]
RateLimitError        httpx-derived=False   status_code == 429
InternalServerError   httpx-derived=False
```

**Zero** OpenAI exceptions derive from `httpx.HTTPError`. So a 429 rate-limit — the
single most common transient failure in this system — is currently treated as a fatal
unknown error and fails the node on the first occurrence. PRD §14 explicitly requires
retry on 429/500/502/503/504.

Affected (all use `AsyncOpenAI`):
- `providers/llm/openai.py` — `complete` (3 attempts), `complete_structured` (3)
- `providers/embeddings/openai.py` (3)
- `providers/image/openai_image.py` (2)

### Defect 2 — Imagen's key-redaction destroys retryability

`providers/image/imagen.py:91-99` catches `httpx.HTTPError` and re-raises a sanitized
`RuntimeError(...) from None`. The redaction is **correct and must be preserved** — the
API key is in the request URL and httpx embeds the full URL in its exception repr. But
it converts *every* error, including a retryable 429/503, into an exception class
`with_retry` will not retry. `@with_retry(max_attempts=2)` on that provider is
currently decorative.

### NOT affected — verify before touching

- `providers/tts/sarvam.py` — **already correct, and deliberately so.** It raises a bare
  `RuntimeError` *only* for `insufficient_quota_error` (genuinely non-retryable) and lets
  every other 429 propagate as `httpx.HTTPStatusError` so the existing classification
  retries it. Its `except RuntimeError: raise` before the generic handler also prevents a
  double `record_failure`. **Do not "fix" this file.**
- `providers/tts/azure.py` — raw httpx + `raise_for_status()`; classified correctly today.
- `providers/avatar/heygen.py` — no `with_retry` at all. Out of scope; do not add one in
  this story.

### The trap — why the obvious fix makes production worse

`record_failure(_PROVIDER_KEY)` is called **inside** the retried function
(`providers/llm/openai.py:131` and `:204`, in `except Exception` before `raise`), and
`@with_retry(max_attempts=3)` wraps that same function.

| | attempts per logical call | `record_failure` calls | logical calls to open breaker |
|---|---|---|---|
| Today (429 not retried) | 1 | 1 | 5 |
| Naive classification fix | 3 | 3 | **2** |

With `FAILURE_THRESHOLD = 5` over `FAILURE_WINDOW_SECONDS = 120`, fixing the
classification alone makes the breaker trip **2.5× faster**, converting a brief
rate-limit into a 10-minute half-open outage across every lesson in flight. **Shipping
AC-1 without AC-3 is a net regression.** They must land together.

## Acceptance Criteria

1. **AC-1 — `with_retry` classifies OpenAI SDK exceptions per PRD §14.**
   `openai.RateLimitError` (429), `openai.InternalServerError` and any
   `openai.APIStatusError` whose `.status_code` is in {429, 500, 502, 503, 504} are
   **retried**. `openai.APITimeoutError` and `openai.APIConnectionError` are **retried**
   (network-class). Backoff stays exactly `(2 ** attempt) + random.random()`.
   - The OpenAI import must not become a hard dependency of `core/retry.py` in a way that
     breaks environments without it — guard the import, and prove with a test that the
     module still imports and still classifies httpx correctly when `openai` is absent.
2. **AC-2 — the non-retryable set is unchanged and still wins.** An `APIStatusError`
   with `.status_code` in {400, 401, 403, 404, 422} raises immediately, zero retries.
   PRD §14: "Never retry: 400, 401". An unclassified status (e.g. 418) also does not retry.
3. **AC-3 — the circuit breaker counts LOGICAL calls, not retry attempts.** One logical
   provider call that internally retries N times must produce **at most one**
   `record_failure`. Prove it with an assertion on call count, for N = max_attempts.
   - This is the AC that makes AC-1 safe to ship. Neither may merge without the other.
   - `FAILURE_THRESHOLD` and `FAILURE_WINDOW_SECONDS` must **not** be retuned to
     compensate — the accounting is what is wrong, not the threshold.
4. **AC-4 — circuit-open behaviour is preserved and cannot self-feed.**
   - A call made while the circuit is already OPEN still raises immediately and is **not**
     retried (today's behaviour, via the unknown-exception branch — it must survive AC-1).
   - The circuit-open rejection must **not** itself call `record_failure`, or the breaker
     feeds itself and can never close.
   - Decide and **document in the story's Dev Agent Record** whether a breaker that opens
     *mid-retry* short-circuits the remaining attempts. Either answer is acceptable; an
     undocumented accident is not. State the chosen semantics and test it.
5. **AC-5 — Imagen retries again without leaking the key.** A retryable httpx error
   inside `imagen.py` is retried per AC-1, while the sanitized message still contains
   **no API key**. Assert both in one test: that the retry happened, and that the key
   string appears nowhere in `str(exc)`, `repr(exc)`, or the captured log output.
   - `from None` and the redaction behaviour must be preserved.
6. **AC-6 — `__cause__` redaction is preserved.** `with_retry`'s unknown-exception branch
   must keep its bare `raise`. A provider's deliberate `raise ... from None` must still
   arrive with `__cause__` intact/None as it intended — `raise exc from exc` previously
   clobbered this and defeated the redaction (2026-07-15 review finding,
   `image_generator_node`). Add a regression test asserting `__cause__` survives.
7. **AC-7 — Sarvam is untouched and still behaves.** `insufficient_quota_error` still
   does **not** retry; a non-quota 429 still does. Regression assertions only — no
   production change to `sarvam.py`.
8. **AC-8 — No regression.** Full suite shows exactly the pre-existing unrelated
   failures — no more, no fewer, compared against baseline commit. `ruff check`,
   `ruff format --check` and `mypy` produce no findings that did not already exist at
   baseline on any touched file.

## Tasks / Subtasks

- [ ] Task 1 (AC-1, AC-2): exception classification in `core/retry.py`, guarded `openai` import; tests for each retryable and non-retryable class.
- [ ] Task 2 (AC-3, AC-4): move breaker accounting out of the retried inner function; decide and document the mid-retry semantics; assert one `record_failure` per logical call.
- [ ] Task 3 (AC-5): make Imagen's sanitized re-raise retryable without leaking the key.
- [ ] Task 4 (AC-6, AC-7): `__cause__` regression test; Sarvam behaviour-preservation tests.
- [ ] Task 5 (AC-8): full suite, lint, types.

## Dev Notes

- **Do not fix AC-1 and ship without AC-3.** See the trap table above. This is the single
  most important constraint in the story.
- **Shape to validate, not to assume.** The suggested refactor is to split breaker
  accounting out of the retried function into a thin outer wrapper:

  ```
  async def complete(...):              # outer: breaker accounting, ONE per logical call
      if await is_circuit_open(k): raise RuntimeError(...)   # must NOT record_failure
      try:
          return await self._complete_inner(...)             # inner: @with_retry
      except Exception:
          await record_failure(k); raise
      # record_success on the happy path
  ```

  Verify this against the real call sites before committing to it. Note `complete` and
  `complete_structured` both need it, and `embeddings` / `openai_image` follow the same
  pattern — four call sites, not one. Consider whether a shared helper or decorator is
  cleaner than four hand-rolled wrappers, but do **not** invent a framework.
- **`with_retry` must not retry the circuit-open `RuntimeError`.** Today that falls out of
  the unknown-exception branch for free. After AC-1 widens classification, confirm it
  still does — a retry loop against an open breaker is pure latency.
- **Cost implications are real.** Retries that now actually happen are billed. Phase-1
  nodes have no `check_ceiling()` gate (confirmed in Story 2-31's review — only planner,
  slides, tts and image call it), so a newly-working retry path increases spend against
  the $3.00/lesson ceiling in a way nothing currently bounds. Flag the exposure in the
  Dev Agent Record; **do not** expand ceiling enforcement in this story — that is its own
  piece of work and would balloon scope.
- **Testing the classification does not need network.** Construct the SDK exceptions
  directly. `APIStatusError` requires a `response` and `body`; build a minimal
  `httpx.Response` for it rather than mocking the whole client.
- Every new test needs `@pytest.mark.unit` (and `@pytest.mark.asyncio` where async).

### Project Structure Notes

Touches `apps/api/app/core/retry.py`, `apps/api/app/core/circuit_breaker.py` (only if
AC-3/AC-4 require it — prefer not to), `apps/api/app/providers/llm/openai.py`,
`apps/api/app/providers/embeddings/openai.py`, `apps/api/app/providers/image/openai_image.py`,
`apps/api/app/providers/image/imagen.py`, and unit tests.

**No** `packages/shared/*` and **no** `supabase/migrations/*` — §16 four-dev gate not
triggered. Zero `apps/web/**` changes.

**Explicitly out of scope:** adding `with_retry` to `providers/avatar/heygen.py`;
expanding `check_ceiling()` coverage to Phase-1 nodes; retuning `FAILURE_THRESHOLD`.

### Branching

`sprint2/dev1-provider-retry-classification`, based on **`main`** (7348852) — unlike
Stories 2-28 and 2-31 this touches `core/` and `providers/` with zero overlap against
those branches, so it does not need to be stacked and can merge independently.

### References

- [Source: DEV1-FIX-PLAN.md — Bug C, Branch 3]
- [Source: CLAUDE.md §14 Failure Modes — retryable/non-retryable codes, backoff formula]
- [Source: docs/stories/2-31-narration-recovery-and-tier-cleanup.md — Phase-1 nodes have no check_ceiling() gate]
- [Source: 2026-07-15 review finding, image_generator_node — `raise exc from exc` clobbered `__cause__`]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-28 | Story created. Covers both defects found during investigation — OpenAI SDK exceptions never classified, and Imagen's key-redaction converting retryable errors into un-retryable `RuntimeError` — plus the circuit-breaker accounting trap that makes the obvious fix a net regression. Confirmed Sarvam and Azure are already correct and must not be changed. | Dev 1 |
