"""Markdown results report for Story 5-1 (`docs/stories/5-1-load-test-50-concurrent.md` AC-9).

`build_report` assembles a single Markdown string from the `ScenarioResult`s
produced by `phase_a_upload.run_phase_a` / `phase_b_generate.run_phase_b`, the
two race-probe outcome dicts (`race_probes.probe_d45_idempotency_race` /
`probe_gate7_concurrency_race`), and a caller-supplied `topology` dict — every
field AC-9 requires a written report to record:

  * topology used (API replica count, worker replica count, `max_jobs`) --
    all three MUST be stated, never assumed (Scale & Load Q3/Q5), so this
    module reads them straight out of `topology` and never invents a default.
  * P99 enqueue (submission) latency
  * P50 / P95 / max real pipeline completion duration
  * crash / error count, Redis error count, cost-ceiling breach count,
    circuit-breaker trip count (and blast radius, when known)
  * D45 / Gate-7 race reproduction outcome

This module does no I/O and makes no HTTP calls -- it is pure string
assembly over data already collected by the scenario runners, so it can be
unit-tested (and sanity-imported) with zero network dependency.
"""

from __future__ import annotations

from typing import Any

from tests.loadtest.models import ScenarioResult

_REDIS_ERROR_MARKERS = (
    "connectionerror",
    "redis",
    "pool timeout",
    "too many connections",
    "connection refused",
)

_CRASH_MARKERS = (
    "500",
    "502",
    "503",
    "504",
    "traceback",
    "internal server error",
)


def _percentile(values: list[float], pct: float) -> float | None:
    """Return the `pct` percentile (0-100) of `values` via a manual
    nearest-rank calculation -- no new dependency, no scipy/numpy.

    Returns None for an empty input (never fabricates a number from nothing;
    the report must say "no data" explicitly rather than print `0.0` for a
    scenario that produced zero samples, e.g. a skipped race probe or a
    smoke run with no completions yet).

    Deliberately NOT `statistics.quantiles` for n=1 (that raises
    StatisticsError below n=2) -- a smoke-scale run with a single completed
    lesson is a real, expected input this report must still render cleanly.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    rank = (pct / 100) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def _fmt(value: float | None, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "N/A (no data)"
    return f"{value:.{digits}f}{unit}"


def _count_matching(errors: list[str], markers: tuple[str, ...]) -> int:
    """Count error strings that contain any of `markers` (case-insensitive
    substring match) -- a best-effort classification over the already-short,
    already-deduped `errors` list every `ScenarioResult` carries, not a new
    query against anything live."""
    count = 0
    for err in errors:
        lowered = err.lower()
        if any(marker in lowered for marker in markers):
            count += 1
    return count


def _scenario_by_name(results: list[ScenarioResult], name: str) -> ScenarioResult | None:
    for result in results:
        if result.scenario == name:
            return result
    return None


def _render_topology(topology: dict[str, Any]) -> str:
    api_replicas = topology.get("api_replicas", "NOT RECORDED")
    worker_replicas = topology.get("worker_replicas", "NOT RECORDED")
    max_jobs = topology.get("max_jobs", "NOT RECORDED")
    extra_lines = [
        f"- {key}: {value}"
        for key, value in topology.items()
        if key not in ("api_replicas", "worker_replicas", "max_jobs")
    ]
    total_execution_concurrency: int | str = "N/A"
    if isinstance(max_jobs, int) and isinstance(worker_replicas, int):
        total_execution_concurrency = max_jobs * worker_replicas
    lines = [
        "## Topology",
        "",
        f"- API replica count: **{api_replicas}**",
        f"- Worker replica count: **{worker_replicas}**",
        f"- `max_jobs` (ARQ, per worker process): **{max_jobs}**",
        f"- Total execution concurrency across deployment (max_jobs x "
        f"worker_replicas, per Scale & Load Q3): **{total_execution_concurrency}**",
    ]
    lines.extend(extra_lines)
    return "\n".join(lines)


def _render_scenario_summary(result: ScenarioResult) -> str:
    lines = [
        f"### `{result.scenario}`",
        "",
        f"- Total requests: {result.total_requests}",
        f"- Succeeded: {result.succeeded}",
        f"- Failed: {result.failed}",
    ]
    if result.extra.get("status_code_counts"):
        counts = result.extra["status_code_counts"]
        pretty = ", ".join(f"{code}: {n}" for code, n in sorted(counts.items()))
        lines.append(f"- Status code counts: {pretty}")
    if result.errors:
        lines.append(f"- Distinct errors observed ({len(result.errors)}, capped/deduped):")
        for err in result.errors:
            lines.append(f"  - `{err}`")
    else:
        lines.append("- Distinct errors observed: none")
    return "\n".join(lines)


def _render_race(name: str, probe: dict[str, Any]) -> str:
    if not probe:
        return f"### {name}\n\n- **SKIPPED** — no probe result available for this run.\n"
    reproduced = probe.get("reproduced")
    verdict = "REPRODUCED" if reproduced else "NOT reproduced (existing mitigation held)"
    lines = [f"### {name}", "", f"- Outcome: **{verdict}**"]
    for key in ("responses", "lesson_ids", "accepted_count", "rejected_count", "status_codes"):
        if key in probe:
            lines.append(f"- `{key}`: {probe[key]}")
    if probe.get("note"):
        lines.append(f"- Note: {probe['note']}")
    return "\n".join(lines)


def build_report(
    results: list[ScenarioResult],
    race_d45: dict[str, Any],
    race_gate7: dict[str, Any],
    topology: dict[str, Any],
) -> str:
    """Assemble the Story 5-1 AC-9 Markdown results report.

    Args:
        results: every `ScenarioResult` produced by this run (Phase A upload,
            Phase B generate -- whichever scenarios actually ran; a smoke run
            may only carry `phase_b_generate`).
        race_d45: the dict returned by
            `race_probes.probe_d45_idempotency_race`, or `{}` if that probe
            was not run this pass (e.g. smoke scale).
        race_gate7: the dict returned by
            `race_probes.probe_gate7_concurrency_race`, or `{}` if skipped
            (e.g. the fixture book had fewer than 4 chapters).
        topology: `{'api_replicas': int, 'worker_replicas': int, 'max_jobs':
            int, ...}` -- the actual environment topology this run executed
            against. AC-9 requires all three be STATED, never assumed; pass
            them explicitly even for a local single-process run
            (e.g. `{'api_replicas': 1, 'worker_replicas': 1, 'max_jobs': 5}`).

    Returns:
        A single Markdown string, suitable for printing to stdout and/or
        writing to `docs/reports/load-test-5-1-results.md`.
    """
    phase_a = _scenario_by_name(results, "phase_a_upload")
    phase_b = _scenario_by_name(results, "phase_b_generate")

    lines: list[str] = [
        "# Story 5-1 — Load Test Results (50 concurrent lesson generations)",
        "",
        "Generated by `apps/api/tests/loadtest/run.py`. Every number below is a real",
        "measurement against the running API + real Supabase project named by this",
        "harness's `.env` — no mocked/simulated data.",
        "",
        _render_topology(topology),
        "",
        "## AC-2 — Phase A (upload) results",
        "",
    ]

    if phase_a is not None:
        p95_ms = _percentile(phase_a.latencies_ms, 95)
        lines.append(_render_scenario_summary(phase_a))
        lines.append("")
        lines.append(f"- P95 submission latency: {_fmt(p95_ms, ' ms')} (target: < 2000 ms)")
        crash_count = _count_matching(phase_a.errors, _CRASH_MARKERS)
        redis_count = _count_matching(phase_a.errors, _REDIS_ERROR_MARKERS)
        lines.append(f"- Crash-like (5xx) error count: {crash_count}")
        lines.append(f"- Redis-connection-error count: {redis_count}")
    else:
        lines.append("- **SKIPPED this run** (e.g. smoke scale only runs Phase B).")
    lines.append("")

    lines.append("## AC-3 — Phase B (generate) results")
    lines.append("")
    if phase_b is not None:
        p99_submit_ms = _percentile(phase_b.latencies_ms, 99)
        completion_s = phase_b.extra.get("completion_durations_s", [])
        p50_completion = _percentile(completion_s, 50)
        p95_completion = _percentile(completion_s, 95)
        max_completion = max(completion_s) if completion_s else None
        terminal_counts = phase_b.extra.get("terminal_status_counts", {})
        never_terminal = terminal_counts.get("never_terminal_timeout", 0)

        lines.append(_render_scenario_summary(phase_b))
        lines.append("")
        lines.append(
            f"- P99 submission (enqueue-latency proxy) latency: "
            f"{_fmt(p99_submit_ms, ' ms')} (target: < 500 ms; "
            f"client-observed, see `extra['submission_latency_note']`)"
        )
        lines.append(
            f"- Pipeline completion duration — P50: {_fmt(p50_completion, ' s')}, "
            f"P95: {_fmt(p95_completion, ' s')}, max: {_fmt(max_completion, ' s')} "
            f"(measurement against a 15-minute / 900s target, not a hard gate — "
            f"queue depth vs. execution time reported separately per AC-3)"
        )
        lines.append(
            f"- Terminal status counts: {terminal_counts} "
            f"({'NONE' if never_terminal == 0 else never_terminal} lesson(s) never "
            f"reached a terminal status within the harness's poll window)"
        )
        crash_count = _count_matching(phase_b.errors, _CRASH_MARKERS)
        redis_count = _count_matching(phase_b.errors, _REDIS_ERROR_MARKERS)
        lines.append(f"- Crash-like (5xx) error count: {crash_count}")
        lines.append(f"- Redis-connection-error count: {redis_count}")
        lines.append(
            f"- Cost-ceiling breach count: "
            f"{phase_b.extra.get('cost_ceiling_breach_count', 'NOT INSTRUMENTED this run')}"
        )
        lines.append(
            f"- Circuit-breaker trip count: "
            f"{phase_b.extra.get('circuit_breaker_trips', 'NOT INSTRUMENTED this run')}"
        )
    else:
        lines.append("- **SKIPPED this run.**")
    lines.append("")

    lines.append("## AC-6 — Circuit breaker")
    lines.append("")
    if phase_b is not None and "circuit_breaker_trips" in phase_b.extra:
        trips = phase_b.extra["circuit_breaker_trips"]
        blast = phase_b.extra.get("circuit_breaker_blast_radius", "unknown")
        lines.append(f"- Provider circuit(s) opened: {trips}")
        lines.append(f"- Blast radius (distinct users affected by an open circuit): {blast}")
    else:
        lines.append(
            "- Not directly instrumented by this harness run — inspect "
            "`circuit:{provider}:state` Redis keys / worker logs for the run window."
        )
    lines.append("")

    lines.append("## AC-7 — D45 idempotency race probe")
    lines.append("")
    lines.append(_render_race("D45 (chapter_id, tier) idempotency race", race_d45))
    lines.append("")

    lines.append("## AC-8 — Gate 7 concurrency race probe")
    lines.append("")
    lines.append(_render_race("Gate 7 per-user concurrency oversubscription race", race_gate7))
    lines.append("")

    lines.append("## Summary for DEFECT-REGISTER.md D129")
    lines.append("")
    total_crashes = sum(
        _count_matching(r.errors, _CRASH_MARKERS) for r in results
    )
    total_redis_errors = sum(
        _count_matching(r.errors, _REDIS_ERROR_MARKERS) for r in results
    )
    lines.append(
        f"- Total crash-like (5xx) errors across all scenarios this run: {total_crashes}"
    )
    lines.append(f"- Total Redis-connection-error occurrences this run: {total_redis_errors}")
    lines.append(
        f"- D45 race: {'REPRODUCED' if race_d45.get('reproduced') else 'not reproduced / skipped'}"
    )
    lines.append(
        f"- Gate 7 race: "
        f"{'REPRODUCED' if race_gate7.get('reproduced') else 'not reproduced / skipped'}"
    )
    lines.append(
        "- D129 status: this run supersedes the prior 'OPEN, NOT TESTED' status with "
        "the real measurements above — update `docs/DEFECT-REGISTER.md` D129 by hand "
        "with this run's date and a link to this report."
    )
    lines.append("")

    return "\n".join(lines)
