"""AC3 (Story 5-4 / S4-4, D49) — a Redis-backed limiter storage must enforce
one ceiling PER DEPLOYMENT, not per process.

Simulates two live API processes (two independent `Limiter` instances, as
`fly.toml`'s `api` group runs more than one under real load — ADR-001 §2)
sharing one Redis-backed `storage_uri`. A burst split across both must be
throttled at the *combined* configured limit, never at the limit multiplied
by the number of simulated processes — that multiplication is D49 itself.

Uses `fakeredis` (already a declared dev dependency, `pyproject.toml`) rather
than a live Redis, monkeypatching `redis.from_url` — the exact call
`limits.storage.redis.RedisStorage.__init__` makes (`self.dependency.from_url
(uri, **options)`, where `self.dependency` is the `redis` module) — so both
`Limiter` instances resolve to the same in-memory `FakeServer`, genuinely
proving cross-instance sharing rather than asserting a mock was called.
"""

from __future__ import annotations

import fakeredis
import pytest
import redis as redis_module
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

pytestmark = pytest.mark.unit


@pytest.fixture
def shared_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every `redis.from_url(...)` call at the SAME FakeServer, so two
    independently constructed storages behave like two processes talking to
    one real shared Redis instance, not two isolated in-memory stores."""
    shared_server = fakeredis.FakeServer()
    monkeypatch.setattr(
        redis_module,
        "from_url",
        lambda uri, **kwargs: fakeredis.FakeRedis(server=shared_server),
    )


def test_two_limiter_instances_share_one_redis_backed_ceiling(shared_fake_redis: None) -> None:
    """The property D49 names directly: N processes must not multiply the
    ceiling by N. Two 'processes' at 5/minute must allow exactly 5 total, not
    10 — half from each side of a burst split across both."""
    limiter_a = Limiter(
        key_func=get_remote_address, storage_uri="redis://shared-fake-instance:6379/0"
    )
    limiter_b = Limiter(
        key_func=get_remote_address, storage_uri="redis://shared-fake-instance:6379/0"
    )

    limit_item = parse("5/minute")
    key = "user:cross-process-sharing-test"

    allowed = sum(
        1
        for i in range(10)
        if (limiter_a if i % 2 == 0 else limiter_b).limiter.hit(limit_item, key)
    )

    assert allowed == 5, (
        f"expected exactly 5 hits allowed (the configured per-deployment "
        f"ceiling shared across both simulated processes), got {allowed} — "
        f"10 would mean each 'process' kept its own independent counter, "
        f"which is D49's exact bug reproduced rather than fixed."
    )


def test_two_memory_backed_limiter_instances_do_not_share_a_ceiling() -> None:
    """Control case, no fakeredis involved: proves the test above is actually
    exercising cross-instance sharing and not some other effect — with the
    CURRENT (D49) default `memory://` storage, two independently constructed
    `Limiter` instances must each enforce their own full 5/minute, i.e. 10
    combined, reproducing the exact silent multiplication D49 describes."""
    limiter_a = Limiter(key_func=get_remote_address, storage_uri="memory://")
    limiter_b = Limiter(key_func=get_remote_address, storage_uri="memory://")

    limit_item = parse("5/minute")
    key = "user:cross-process-sharing-control"

    allowed = sum(
        1
        for i in range(10)
        if (limiter_a if i % 2 == 0 else limiter_b).limiter.hit(limit_item, key)
    )

    assert allowed == 10, (
        "control case: two memory:// Limiter instances are expected to NOT "
        "share state (that is D49) — if this ever starts failing, either "
        "slowapi/limits changed memory:// semantics or this test file's "
        "premise needs re-checking before trusting the fakeredis test above."
    )
