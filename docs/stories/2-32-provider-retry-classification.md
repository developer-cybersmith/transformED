---
baseline_commit: da8b247
---

# Story 2.32: Provider retry exception classification + circuit-breaker accounting

Status: review

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
single most common transient failure in this system — reaches `with_retry` as an
unclassifiable error and is never retried by *our* layer. PRD §14 explicitly requires
retry on 429/500/502/503/504.

> **Corrected 2026-07-29 after review.** This section originally said a 429 "fails the node
> on the first occurrence". That is not true operationally: the OpenAI SDK defaults to
> `max_retries=2`, so it had already retried twice before the exception reached us. The
> class-hierarchy finding above is correct and the classification bug is real; the
> failure-mode narrative built on it was not — and that error is precisely what hid
> `DEV1-FIX-PLAN.md` item 4.4 (`max_retries=0`). See the Dev Agent Record.

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
7. **AC-7 — ~~Sarvam is untouched~~ Sarvam's BEHAVIOUR is unchanged; its accounting moved.**

   > **AMENDED 2026-07-29 after review.** As written this AC said "no production change to
   > `sarvam.py`", on the premise that Sarvam was unaffected. That premise is false and its
   > own source contradicts it: `DEV1-FIX-PLAN.md` item 4.14 explicitly required widening to
   > `tts/azure.py`, `tts/sarvam.py` and `image/imagen.py` because they "already triple-count
   > against the same threshold and are mis-tuned in production **right now**". Verified
   > against baseline `da8b247`: a non-quota 429 gave 3 attempts and 3 `record_failure` calls.
   > The constraint is therefore rewritten to what actually matters — the quota/rate-limit
   > *behaviour* is unchanged — and the accounting fix applies. Original text preserved below,
   > struck through, so the change is auditable.

   ~~Regression assertions only — no production change to `sarvam.py`.~~ `insufficient_quota_error` still
   does **not** retry; a non-quota 429 still does — pinned by tests, not by leaving the
   file untouched.
8. **AC-8 — No regression.** Full suite shows exactly the pre-existing unrelated
   failures — no more, no fewer, compared against baseline commit. `ruff check`,
   `ruff format --check` and `mypy` produce no findings that did not already exist at
   baseline on any touched file.

## Tasks / Subtasks

- [x] Task 1 (AC-1, AC-2): exception classification in `core/retry.py`, guarded `openai` import; tests for each retryable and non-retryable class.
- [x] Task 2 (AC-3, AC-4): move breaker accounting out of the retried inner function; decide and document the mid-retry semantics; assert one `record_failure` per logical call.
- [x] Task 3 (AC-5): make Imagen's sanitized re-raise retryable without leaking the key.
- [x] Task 4 (AC-6, AC-7): `__cause__` regression test; Sarvam behaviour-preservation tests.
- [x] Task 5 (AC-8): full suite, lint, types.

## Dev Agent Record

### Completion Notes

**AC-1 — classification.** `with_retry` gained an `_OPENAI_API_ERRORS` branch that mirrors
the httpx branches, dispatching on `exc.status_code` (which `APIStatusError` subclasses
carry) and falling back to type for the network class. Backoff is untouched.

**A bug I introduced and had to fix, worth reading.** My first guarded import caught only
`ImportError`. That is not enough: parts of the suite install
`sys.modules["openai"] = MagicMock()`, so the import "succeeded" and bound *Mock attributes*
into the `except (...)` tuple, producing
`TypeError: catching classes that do not inherit from BaseException` on **every** provider
call — a transient 429 would have become a hard TypeError in production. Fixed with
`_exception_classes()`, which keeps only real `BaseException` subclasses so a stubbed SDK
degrades to httpx-only classification. Regression test:
`test_guarded_import_ignores_a_non_class_openai_stub`.

**Two stale `openai` stubs removed.** `openai>=1.40.0` is a declared hard dependency, yet
`tests/conftest.py` and `test_provider_tracing_resilience.py` both did
`sys.modules.setdefault("openai", MagicMock())` — the latter at *module* level, i.e. at
collection time, so whichever ran first won. Provider tests were asserting against a
MagicMock rather than the real exception hierarchy, and this AC cannot be proven without
real `openai.APIStatusError` instances. Both now defer to the real SDK and stub only if the
import genuinely fails.

**AC-3 — the trap, measured.** Before the fix, one logical `complete()` call against a 429
recorded **3** failures (asserted at `assert 3 == 1` in the RED phase). `guard_breaker` now
sits outside the retry decorator and records exactly one outcome per logical call. Applied
to **six** call sites, not the four the story anticipated — see AC-7 note below.

**AC-4 — mid-retry semantics, decided and documented.** `is_circuit_open` is checked on
**every** attempt, inside the retried function. If concurrent traffic trips the breaker
while we are backing off, the remaining attempts short-circuit rather than hammer a provider
already known to be down. The rejection is a new `CircuitOpenError` (a `RuntimeError`
subclass, so existing `except RuntimeError` guards are unaffected) which `guard_breaker`
deliberately does **not** count — counting a rejection would let the breaker feed itself and
never close. Test: `test_circuit_opening_mid_retry_short_circuits_remaining_attempts`.

**AC-5 — Imagen.** Redaction and retryability were mutually exclusive because the sanitized
re-raise was a bare `RuntimeError`. New `SanitizedHTTPError(RuntimeError)` carries
`status_code` — metadata, never the URL — so `with_retry` applies the PRD §14 rules to a
redacted error. `from None` preserved. The test asserts retry **and** absence of the key in
`str`, `repr` and captured logs together, so a fix that restored retry by dropping
sanitization would fail it.

**AC-7 — DEVIATION, please read.** The story said "no production change to `sarvam.py`",
written on the assumption Sarvam was unaffected. It is unaffected on *classification* but
**not** on *accounting*: because its httpx errors were always classified, Sarvam always
retried, and therefore has **always** recorded `max_attempts` failures per logical call.
Measured on the unmodified code: 3 post attempts -> 3 `record_failure` calls. The TTS
breaker has been tripping ~3x too fast in production, independent of this story. Azure is
the same.

I applied the accounting fix to both, because AC-3 is unscoped ("the circuit breaker counts
LOGICAL calls") and this is a live defect. AC-7's *testable* content — `insufficient_quota_error`
does not retry, a non-quota 429 does — is preserved exactly and now pinned by two additional
tests plus the four pre-existing `test_sarvam_*` tests. **If the reviewer disagrees with
touching `sarvam.py`/`azure.py`, the fix is separable**: revert those two files and the
pre-existing defect simply remains.

**Structural guard.** `test_tts_providers_no_longer_record_breaker_outcomes_themselves`
asserts no provider module imports `record_failure`/`record_success` directly. Re-adding one
would silently return that provider to counting attempts — a regression no behavioural test
would obviously catch.

**Cost exposure, flagged not fixed (per Dev Notes).** Retries that now actually happen are
billed, and Phase-1 nodes have no `check_ceiling()` gate (established in Story 2-31's
review). Expanding ceiling enforcement is deliberately out of scope here.

**Mutation-proven.** Four mutations, all killed: dropping OpenAI classification (13 tests
red), not retrying OpenAI network errors, counting a circuit-open rejection as a failure,
and making `SanitizedHTTPError` un-retryable.

**AC-8 — regression.** Full suite **24 failed, 1352 passed, 3 skipped** vs baseline
`da8b247` **24 failed, 1317 passed, 3 skipped** — **+35 passing, zero new failures**,
failure sets byte-identical under `diff`. `ruff check` and `ruff format --check`: clean on
all 14 touched files. `mypy`: clean on all 8 touched source files.


### Senior Developer Review — 6-layer adversarial round, 2026-07-29

Layers: Blind Hunter (diff-only security), Edge Case Hunter, Acceptance Auditor,
Story Quality, Test Coverage (mutation), Process Integrity. **Outcome: Changes Requested,
all applied below.** Every finding I acted on was reproduced by me before fixing.

**The finding that mattered most — I dropped half of my own plan.**
`DEV1-FIX-PLAN.md` item 4.4 required `max_retries=0` + explicit timeouts on all three
OpenAI clients, with a TRAP callout in the plan itself: *"SDK default is `max_retries=2`
→ naive fix = 9 HTTP requests per logical call and up to 3x600s hangs vs
`arq_job_timeout_s`."* I wrote the story from that plan and omitted it. Verified:
`openai._constants.DEFAULT_MAX_RETRIES == 2`, `DEFAULT_TIMEOUT` read = 600s, and all three
clients were bare `AsyncOpenAI(api_key=...)`. So AC-1 as first shipped multiplied an
already-retrying SDK — 3 x 3 = **nine HTTP requests** per logical call with two independent
backoff schedules. Fixed: `max_retries=0` and an explicit
`httpx.Timeout(settings.openai_request_timeout_s, connect=5.0)` on each client, plus a
separate `openai_image_request_timeout_s` (180s) since image calls are legitimately slower.
The timeout is deliberately **not** a bare float: a bare float sets `connect` to the same
value, replacing the SDK's 5s connect guard and making a connect hang strictly worse — also
called out in the plan and now asserted by
`test_openai_clients_disable_sdk_retries_and_set_explicit_timeouts`.

*Attempt-budget trade, stated explicitly (plan item 4.13):* with `max_retries=0`, the image
providers' `max_attempts=2` is a drop from today's effective 6 HTTP attempts. I kept 2
because PRD §14 is normative — "3 attempts critical, 2 optional" — and image generation is
the optional path with a documented fallback cascade.

**A live credential leak, pre-existing but mine now.** `raise SanitizedHTTPError(...) from
None` sets `__cause__ = None` and `__suppress_context__ = True`, but the raise statement
still binds `__context__` to the httpx exception — and a real `raise_for_status()` message
embeds the full request URL, API key included. Verified: `str(exc.__context__)` and
`repr(exc.__context__)` both contain the key; default traceback formatting does not, so
only consumers that walk the chain directly (structlog, custom formatters, ad-hoc repr
debugging) leak. Assigning `__context__ = None` before the raise does **not** work — the
raise re-binds it. The only reliable fix is to build the sanitized error inside the `except`
block and raise it **after** the block exits, which is what `imagen.py` now does, with the
reasoning inline so nobody "simplifies" it back. My original test asserted only
`__cause__ is None`; `test_sanitized_error_does_not_retain_the_original_via_context` now
asserts the real property.

**My flagship AC-5 test was theatre.** It built the fixture as
`httpx.HTTPStatusError("503", request=..., response=...)`, whose `str()` is literally
`"503"` — the key lived only in `request.url`. Deleting the sanitization entirely left all
three no-leak assertions green, the 503 retried by the httpx branch, and `__cause__ is None`
satisfied. **The whole test survived the mutation it advertised killing.** The fixture now
carries a realistic `raise_for_status()`-style message, with an in-test assertion that the
fixture *can* leak — otherwise it proves nothing.

**AC-5 was only half-implemented.** `httpx.HTTPError` also covers
`TimeoutException`/`ConnectError`/`ReadError`, which have no `.response` and so produced
`status_code=None` → the "cannot classify, do not retry" branch. The most common transient
failure of an outbound HTTP call was still permanently fatal for Imagen. `SanitizedHTTPError`
gained `network_error`, set from `isinstance(exc, httpx.TimeoutException | httpx.NetworkError)`.

**A latent CI flake that broke AC-5 non-deterministically.** The AC-1 absence test used
`importlib.reload(app.core.retry)`, which rebinds `SanitizedHTTPError` to a new class object.
`imagen.py` holds the old one, so the reloaded `with_retry`'s `except SanitizedHTTPError`
stops matching and Imagen retry silently dies for the rest of the session. Deterministic
repro, confirmed on `fab4131`: running `test_image_providers.py`, then that one test, then
`test_breaker_accounting.py` fails `test_imagen_retryable_error_...`. It passed only because
alphabetical collection happened to order the files favourably. The check now runs in a
**subprocess**, which has no shared class identity. Verified order-independent in both
directions afterwards.

**Azure had zero AC-3 coverage** — a mutation reinstating per-attempt `record_failure` there
(via an aliased module import, which evades the structural `hasattr` guard) left the entire
suite green. Azure is the production TTS fallback. Added
`test_azure_retries_but_records_one_failure`, and the structural guard now also asserts
`guard_breaker(` is *present* (deleting the wrapper entirely previously satisfied it) and
inspects source text to close the alias bypass.

**Two breaker misclassifications, both able to cause a self-inflicted outage.**
- A cost-ceiling abort raised a plain `RuntimeError` from inside the retried body, so
  `guard_breaker` counted it as provider ill-health. Five ceiling breaches across concurrent
  lessons would open the **shared** `openai` circuit for ten minutes, for every lesson — the
  cost control causing an outage by working correctly. New `CostCeilingError` (still a
  `RuntimeError` subclass, so `content_pipeline_job`'s `"cost ceiling" in str(exc)` branch is
  untouched) is excluded from counting. This is plan item 4.8, also dropped from the story.
- Client-side errors (400/422) counted as provider failures, so uploads that reliably trip a
  content-policy rejection could open the breaker for every tenant. `_is_client_error` reuses
  `_NON_RETRYABLE_STATUS_CODES` and is deliberately narrow — an *unknown* exception still
  counts, because failing to open on a real outage is worse than opening spuriously.
  `test_provider_errors_still_count` guards that the exclusions did not gut the breaker.

**Observability.** `CircuitOpenError` fell through to `logger.exception("Unexpected error")`
at ERROR with a full traceback, so Sentry's default `LoggingIntegration(event_level=ERROR)`
turned every routine rejection into an issue — hundreds over a 600s recovery window, exactly
when logs need to stay readable. It now has its own branch logging at WARNING with a distinct
message, still not retried. Separately, `_OPENAI_API_ERRORS` degrading to `()` was completely
silent; it now logs a warning at import, and the guard catches `AttributeError` as well as
`ImportError` (a circular import yields a partially-initialised module).

**Bookkeeping can no longer displace the result.** `record_success`/`record_failure` were
un-guarded, so a Redis outage would throw away an already-billed completion, or replace the
provider exception `with_retry` needs to classify. Both now go through `_safe_record`.

**A regression my own verification hid.** `tests/test_llm_provider_smoke.py` still patched
`record_success`/`record_failure` on the LLM provider module. It is gated on
`OPENAI_API_KEY`, so it *skips* locally — my "zero new failures" claim was true only in the
key-absent configuration, and CI with a key exported would have errored. Patch targets fixed;
with a fake key it now runs and fails on the network call rather than erroring at setup. **I
cannot verify its pass path without real credentials** — flagging rather than claiming.

**A factual error in my own record, corrected.** I wrote that "Phase-1 nodes have no
`check_ceiling()` gate" and used it to argue urgency. Verified false:
`_fan_out_phase1_economy_nodes` gates before the whole Phase-1 fan-out, and
`_maybe_accumulate_cost` enforces per-call. The narrow claim (`quiz_generator_node` itself
does not call it) is true; the generalisation was not. **The same wrong claim also appears in
Story 2-31's AC-3 text, its Dev Agent Record, the dev1-tracker entry, and PR #101's body** —
corrected there too. It changes no code decision, but a reviewer relying on it would be misled.

**Overstatement corrected.** My record said the MagicMock/`except`-tuple bug "would have
become a hard TypeError in production". It would not: the hazard needs a `MagicMock` in
`sys.modules["openai"]`, which only ever occurred in the test suite. Production has the real
SDK, where the ImportError-only guard was sufficient. The fix is still right — the guard
should not depend on that being true — but the risk was test-only.

**Deliberately deferred, written down rather than dropped:** `Retry-After` header support
(OpenAI returns it on 429; our backoff ignores it, so parallel segment calls retry in a
~1s band — a synchronised wave against a provider already rate-limiting); exactly-once
tracing/cost accounting, which is still per-attempt while breaker accounting is now
per-logical-call (plan 4.9); `FAILURE_THRESHOLD` retuning for the flapping-provider case,
where any interleaved success wipes the counter (pre-existing, unchanged by this story);
and the plan's `test_image_providers.py` fixture that feeds an `httpx.HTTPStatusError` to a
mocked OpenAI client — a type the real SDK never raises (plan 4.11).

**Verification after the round.** Full suite **24 failed / 1360 passed / 3 skipped** vs
baseline `da8b247` **24 failed / 1317 passed / 3 skipped** — **+43 passing, failure sets
byte-identical under `diff`**, and now verified **order-independent** (retry-first and
retry-last both give 88/88 on the affected files). `ruff check`, `ruff format` and `mypy`
clean on all 17 touched files. Nine mutations applied and killed: SDK retries re-enabled,
Imagen raise moved back inside the `except`, network errors marked non-retryable,
cost-ceiling counted, client errors counted, OpenAI classification dropped, non-retryable
check removed, unclassified check removed, `_exception_classes` unfiltered.

### File List

- `apps/api/app/core/retry.py`
- `apps/api/app/core/circuit_breaker.py`
- `apps/api/app/providers/llm/openai.py`
- `apps/api/app/providers/embeddings/openai.py`
- `apps/api/app/providers/image/openai_image.py`
- `apps/api/app/providers/image/imagen.py`
- `apps/api/app/providers/tts/sarvam.py` — see AC-7 deviation
- `apps/api/app/providers/tts/azure.py` — see AC-7 deviation
- `apps/api/tests/conftest.py`
- `apps/api/tests/unit/test_retry.py`
- `apps/api/tests/unit/test_breaker_accounting.py` — NEW
- `apps/api/tests/unit/test_image_providers.py`
- `apps/api/tests/unit/test_tts_providers.py`
- `apps/api/tests/unit/test_provider_tracing_resilience.py`
- `apps/api/tests/test_llm_provider_smoke.py` — stale patch targets (review round)
- `apps/api/app/config.py` — OpenAI transport timeouts (review round)
- `apps/api/app/core/cost_tracker.py` — `CostCeilingError` (review round)
- `apps/api/.gitignore`
- `docs/dev1-tracker.md`

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
| 2026-07-29 | **6-layer adversarial review round — Changes Requested, all applied.** Restored `DEV1-FIX-PLAN.md` item 4.4 (`max_retries=0` + explicit timeouts), which the story had dropped and without which AC-1 meant 9 HTTP requests per logical call. Fixed a live `__context__` credential leak, an AC-5 test that survived its own mutation, Imagen network errors never retrying, a reload-induced CI flake that silently disabled AC-5, missing Azure AC-3 coverage, cost-ceiling and client-side errors counting as provider ill-health, circuit-open rejections logged as ERROR into Sentry, unguarded breaker bookkeeping, and a smoke-test regression my key-absent verification had hidden. AC-7 amended in place; the story's operational premise and a false cost-ceiling claim corrected. | Dev 1 |
| 2026-07-28 | All 5 tasks implemented. Found and fixed a bug in my own first implementation (an ImportError-only guard bound MagicMock attributes into an `except` tuple, turning every provider error into a TypeError). Removed two stale `openai` MagicMock stubs that were making provider tests assert against a mock. **AC-7 deviation:** Sarvam and Azure were found to have the accounting defect already — they always retried, so they always recorded 3 failures per logical call — so the fix was applied to 6 call sites, not 4. Status → review. | Dev 1 |
| 2026-07-28 | Story created. Covers both defects found during investigation — OpenAI SDK exceptions never classified, and Imagen's key-redaction converting retryable errors into un-retryable `RuntimeError` — plus the circuit-breaker accounting trap that makes the obvious fix a net regression. Confirmed Sarvam and Azure are already correct and must not be changed. | Dev 1 |
