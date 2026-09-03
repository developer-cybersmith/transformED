"""Shared data contracts for the Story 5-1 load-testing harness.

Every other module under `tests/loadtest/` (provisioning, fixtures, the two
phase scenarios, the race probes, and whatever runner ties them together)
imports `TestUser` and `ScenarioResult` from HERE and only here. This file is
intentionally tiny and dependency-free (stdlib `dataclasses` only) so it can
be imported by any piece of the harness without pulling in `httpx`,
`app.config`, or a live Supabase connection — a piece that only needs the
*shape* of a result should never need network libraries just to type-check.

`TestUser` carries exactly what an HTTP call needs to act as one real,
authenticated principal: a Supabase `auth.users.id` (`user_id`), the email it
was minted for (useful in error messages / logs, and to distinguish a
disposable Phase B user from a reused Phase A approved account), and a real
access token obtained via the service-role Admin API magic-link flow (see
`provisioning.py`) — never a self-minted token, which this project's
asymmetric JWT Signing Keys reject outright.

`ScenarioResult` is the one shape every load scenario (Phase A upload, Phase B
generate, the D45 probe, the Gate-7 probe) reduces its raw HTTP outcomes down
to, so a final report/runner can aggregate heterogeneous scenarios uniformly
without knowing each one's internal detail. `latencies_ms` is deliberately
SUBMISSION latency (HTTP request -> HTTP response), never pipeline completion
time — Story 5-1 AC-3 requires queue-wait and execution-duration to be
reported as separate numbers, and those separate numbers belong in `extra`
(e.g. `extra["completion_durations_s"]`, `extra["queue_depth"]`), not folded
into `latencies_ms`.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(repr=False)
class TestUser:
    """One real, authenticated test principal.

    `user_id` is the real Supabase `auth.users.id` (a UUID string) — looked up
    live or minted live, never guessed or hardcoded, since a project reset can
    change every UUID (see `provisioning.get_approved_test_users`'s live
    email->id lookup).

    `access_token` is a real, currently-valid access token for this user,
    obtained via the service-role Admin API `generate_link` + redirect-
    fragment flow (`provisioning.mint_real_access_token`). It is a live
    credential for the duration of the harness run.

    `repr=False` above plus the hand-written `__repr__` below are load-bearing,
    not decoration: this dataclass's default `repr()` would otherwise print
    `access_token` in FULL (a live, currently-valid Supabase session token) any
    time a `TestUser` is passed to `logger.*`, an assertion failure message, or
    a debugger/print — a real credential-leak-to-logs risk for a harness whose
    whole job is minting real live sessions. The override below is the actual
    enforcement of that rule, not just a comment asking callers to remember it.
    """

    user_id: str
    email: str
    access_token: str

    def __repr__(self) -> str:
        token_prefix = self.access_token[:8] + "..." if self.access_token else "<empty>"
        return (
            f"TestUser(user_id={self.user_id!r}, email={self.email!r}, "
            f"access_token={token_prefix!r})"
        )


@dataclasses.dataclass
class ScenarioResult:
    """Aggregated outcome of one load-test scenario run.

    `scenario`: a short machine-readable name, e.g. `'phase_a_upload'`,
    `'phase_b_generate'`, `'race_d45_idempotency'`, `'race_gate7_concurrency'`.

    `total_requests` / `succeeded` / `failed`: request-level tallies. What
    counts as "succeeded" is scenario-specific (e.g. Phase A: HTTP 202: Phase
    B generate: HTTP 202 accepted for enqueue, not pipeline completion) and
    must be documented in the scenario's own docstring, not here.

    `errors`: short, deduped, human-readable error strings (status code +
    truncated body snippet, or `"{ExceptionType}: {message}"` for a
    transport-level failure) — NEVER a full traceback or a full response
    body. Cap this list (e.g. `sorted(set(...))[:20]`) so 50 near-identical
    429s do not produce 50 near-identical lines.

    `latencies_ms`: one entry per request, in milliseconds, measured as
    submission latency (time to receive the HTTP response), never pipeline
    completion time.

    `extra`: scenario-specific fields that do not fit the fixed shape above —
    e.g. `status_code_counts`, `completion_durations_s` (Phase B, per AC-3),
    `cost_ceiling_breach_count`, `circuit_breaker_trips`, `queue_depth`,
    or a race probe's `reproduced` / `accepted_count` outcome. Left as a plain
    `dict` (not a nested dataclass) deliberately, since each scenario's extra
    fields differ and a single shared schema would either be too narrow or
    force every scenario to import every other scenario's shape.
    """

    scenario: str
    total_requests: int
    succeeded: int
    failed: int
    errors: list[str]
    latencies_ms: list[float]
    extra: dict[str, Any]
