"""Companion harvester for load-test run #10 -- runs ALONGSIDE the real
harness (tests/loadtest/run.py --scale full), never modifying it. Polls
`lessons` for rows created since this run started, and as soon as each
reaches a terminal status (ready/failed), grabs it before the harness's own
end-of-run cleanup deletes the disposable users (and cascades away their
books/chapters/lessons):

  - real per-lesson total cost (Redis `cost:{lesson_id}`, backend for
    core.cost_tracker.accumulate_cost -- survives independently of the
    Postgres row, 24h TTL)
  - every real slide image (Supabase Storage `lesson-images` bucket)
  - every real narration audio clip (Supabase Storage `lesson-audio` bucket)
  - per-segment audio_provider (sarvam/azure/browser) and per-slide
    image presence, straight from the real stored LessonPackage content

Writes one folder per lesson under OUTPUT_DIR, plus a final aggregate
summary.json once no new terminal lessons have appeared for a while.
Not a permanent test file -- deleted after use.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.core.db import get_supabase
from app.core.redis import get_redis, init_redis

OUTPUT_DIR = Path("scratch_load_test_media")
POLL_INTERVAL_S = 8
# Found live during run #10: a terminal lesson's Redis cost:{lesson_id} key is
# already DELETED by content_pipeline.py's clear_lesson_cost() once the
# pipeline finishes -- the real, durable total is persisted to
# lesson_jobs.cost_usd instead. Redis is kept only as a fallback for a
# lesson this harvester catches mid-flight (shouldn't normally happen since
# only ready/failed rows are harvested, but a cleared-and-not-yet-persisted
# race is cheaper to guard against than to prove impossible).
IDLE_ROUNDS_BEFORE_STOP = 45  # ~360s of no new terminal lessons -- real completions trickle in
# over several minutes, not a tight cluster; the original 96s cut the run #10
# harvest off after only 4 of what became dozens of real lessons.
_MAX_RUNTIME_S = 25 * 60  # hard backstop in case nothing is ever harvested (e.g. every lesson hangs)


async def _get_lesson_cost(supabase: Any, lesson_id: str) -> float | None:
    # Primary source: lesson_jobs.cost_usd, the durable value
    # content_pipeline.py persists once the pipeline reaches a terminal
    # state -- Redis's cost:{lesson_id} is already deleted by then.
    try:
        resp = (
            supabase.table("lesson_jobs")
            .select("cost_usd")
            .eq("lesson_id", lesson_id)
            .maybe_single()
            .execute()
        )
        if resp.data and resp.data.get("cost_usd") is not None:
            return float(resp.data["cost_usd"])
    except Exception as exc:  # noqa: BLE001 -- harvester must never crash the run
        print(f"  [warn] could not read lesson_jobs.cost_usd for {lesson_id}: {exc}")

    # Fallback: Redis, in case this lesson was caught before the pipeline's
    # own clear_lesson_cost() ran (shouldn't normally happen for a row this
    # harvester already sees as ready/failed, but cheaper to guard than assume).
    try:
        redis = get_redis()
        raw = await redis.get(f"cost:{lesson_id}")
        return float(raw) if raw is not None else None
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] could not read Redis cost fallback for {lesson_id}: {exc}")
        return None


async def _download(supabase: Any, bucket: str, path: str, dest: Path) -> bool:
    try:
        data = await asyncio.to_thread(supabase.storage.from_(bucket).download, path)
        dest.write_bytes(data)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] download failed {bucket}/{path}: {exc}")
        return False


async def harvest_one(supabase: Any, row: dict[str, Any]) -> dict[str, Any]:
    lesson_id = row["lesson_id"]
    status = row["status"]
    out_dir = OUTPUT_DIR / lesson_id
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "lesson_id": lesson_id,
        "status": status,
        "book_id": row.get("book_id"),
        "chapter_id": row.get("chapter_id"),
        "total_cost_usd": await _get_lesson_cost(supabase, lesson_id),
    }

    if status != "ready" or not row.get("content"):
        summary["error"] = row.get("error_message") or row.get("error")
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    content = row["content"]
    segments = content.get("segments", [])
    images_saved = 0
    images_missing = 0
    audio_saved = 0
    audio_by_provider: dict[str, int] = {}
    segment_details = []

    for seg in segments:
        seg_detail: dict[str, Any] = {"segment_id": seg.get("segment_id"), "slides": []}

        narration = seg.get("narration") or {}
        provider = narration.get("audio_provider", "unknown")
        audio_by_provider[provider] = audio_by_provider.get(provider, 0) + 1
        audio_path = narration.get("audio_url")
        if audio_path and provider in ("sarvam", "azure"):
            dest = out_dir / f"{seg.get('segment_id')}.mp3"
            if await _download(supabase, "lesson-audio", audio_path, dest):
                audio_saved += 1
        seg_detail["audio_provider"] = provider

        for slide in seg.get("slides", []):
            slide_id = slide.get("slide_id")
            image_path = slide.get("image_url")
            has_image = bool(image_path)
            seg_detail["slides"].append({"slide_id": slide_id, "has_image": has_image})
            if has_image:
                dest = out_dir / f"{slide_id}.png"
                if await _download(supabase, "lesson-images", image_path, dest):
                    images_saved += 1
                else:
                    images_missing += 1
            else:
                images_missing += 1

        segment_details.append(seg_detail)

    summary["segment_count"] = len(segments)
    summary["images_saved"] = images_saved
    summary["images_missing_or_text_only"] = images_missing
    summary["audio_saved"] = audio_saved
    summary["audio_by_provider"] = audio_by_provider
    summary["segments"] = segment_details

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


async def main() -> None:
    start_iso = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).isoformat()
    print(f"Harvester watching lessons created >= {start_iso}")

    await init_redis(get_settings().redis_url)
    supabase = get_supabase()

    harvested: dict[str, dict[str, Any]] = {}
    idle_rounds = 0
    max_rounds = int(_MAX_RUNTIME_S / POLL_INTERVAL_S)  # hard backstop if nothing ever harvests
    round_count = 0

    while idle_rounds < IDLE_ROUNDS_BEFORE_STOP and round_count < max_rounds:
        round_count += 1
        resp = (
            supabase.table("lessons")
            .select("*")
            .gte("created_at", start_iso)
            .execute()
        )
        new_this_round = 0
        for row in resp.data or []:
            lesson_id = row["lesson_id"]
            if lesson_id in harvested:
                continue
            if row.get("status") in ("ready", "failed"):
                print(f"  harvesting {lesson_id} (status={row['status']})")
                summary = await harvest_one(supabase, row)
                harvested[lesson_id] = summary
                new_this_round += 1

        # Only start counting "idle" rounds once at least one lesson has ever
        # been harvested -- otherwise this would give up long before Phase B
        # even starts creating lessons (fixture setup alone can take minutes).
        if harvested:
            idle_rounds = 0 if new_this_round else idle_rounds + 1
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] harvested so far: {len(harvested)} "
            f"(idle rounds: {idle_rounds}/{IDLE_ROUNDS_BEFORE_STOP})"
        )
        await asyncio.sleep(POLL_INTERVAL_S)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_cost = sum(s["total_cost_usd"] for s in harvested.values() if s.get("total_cost_usd"))
    ready = [s for s in harvested.values() if s["status"] == "ready"]
    failed = [s for s in harvested.values() if s["status"] == "failed"]
    total_images = sum(s.get("images_saved", 0) for s in harvested.values())
    total_audio = sum(s.get("audio_saved", 0) for s in harvested.values())

    aggregate = {
        "lessons_harvested": len(harvested),
        "ready": len(ready),
        "failed": len(failed),
        "sum_of_real_per_lesson_costs_usd": round(total_cost, 4),
        "total_images_saved": total_images,
        "total_audio_clips_saved": total_audio,
        "lesson_ids": list(harvested.keys()),
    }
    (OUTPUT_DIR / "AGGREGATE_SUMMARY.json").write_text(json.dumps(aggregate, indent=2))
    print("=== HARVESTER DONE ===")
    print(json.dumps(aggregate, indent=2))


asyncio.run(main())
