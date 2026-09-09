'use client';

import { useMemo } from 'react';
import { usePlayerStore } from '@/stores/player.machine';
import type { CaptionLine } from '@hie/shared/types/lesson';

interface CaptionOverlayProps {
  /** Current segment's full narration script. Pass `segment?.narration.script ?? null`. */
  script: string | null;
  /**
   * Real server-side line timing (Story 4-29 / BR-6), when present on the segment's
   * `Narration`. When non-empty, this is the source of truth for both line text and
   * timing -- the proportional client-side estimate below is only used as a fallback
   * for older lesson records or the browser-TTS/`tinytag`-failure degraded case where
   * the server could not measure a real audio duration (Story 4-29 AC5).
   */
  captionLines?: CaptionLine[];
}

// Review redesign (2026-08-17): was "show the whole segment script at once,
// non-synced" (Story 3-53 / D90). Replaced with YouTube/Netflix-style one-line
// captions that advance as the segment plays -- the whole-script version had a
// separate, since-fixed bug where the resulting scroll was completely
// unreachable (pointer-events-none + missing data-lenis-prevent), but even
// fixed, "read a whole paragraph inside a 30%-height scrollable box" was never
// the actual product intent; the ask is a caption *line*, current to what's
// being narrated right now.
//
// UPDATE (Story 2-61 / BR-3, 2026-09-09): `Narration.caption_lines` (Story 4-29 /
// BR-6) now provides real, server-side line text + `start_ms`/`end_ms` estimated
// from the actual measured audio duration -- see `activeCaptionLineIndexFromTimestamps`
// below, which is used whenever `captionLines` is present. There is still no
// word-level timing anywhere in the pipeline (`NarrationTimestamp` remains
// per-SLIDE, and no TTS provider in the fallback chain returns word-level timing),
// so a frame-perfect, word-highlighted sync (true YouTube auto-caption behaviour)
// remains out of reach -- but LINE-level sync to a real measured duration is now
// real, not estimated.
//
// The functions immediately below (`splitScriptIntoCaptionLines` /
// `activeCaptionLineIndex`) remain the deliberate fallback for the degraded case
// where `caption_lines` is empty or absent (older lesson records predating this
// field, the browser-TTS fallback, or a `tinytag` failure at generation time --
// Story 4-29 AC5): split the script into short, subtitle-length lines and estimate
// each line's time window by allocating the segment's total known duration
// proportionally to each line's character count. This is still an approximation
// on that path only -- pacing, pauses, and emphasis all shift true timing -- but it
// tracks actual playback position and never requires scrolling to read a line.

// ~10 words is close to broadcast-subtitle convention (roughly one breath /
// one glance's worth of reading) and keeps every line short enough that the
// overflow-y-auto/data-lenis-prevent fallback below should never actually be
// needed in practice.
const WORDS_PER_LINE = 10;

/** Exported for unit testing. Empty/whitespace-only input yields []. */
export function splitScriptIntoCaptionLines(script: string): string[] {
  const words = script.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const lines: string[] = [];
  for (let i = 0; i < words.length; i += WORDS_PER_LINE) {
    lines.push(words.slice(i, i + WORDS_PER_LINE).join(' '));
  }
  return lines;
}

/**
 * Which line index is "active" at `positionMs`, given each line's estimated
 * duration is proportional to its own character count within `totalMs`.
 * Exported for unit testing.
 *
 * `totalMs <= 0` (duration not yet known -- e.g. real audio hasn't fired
 * `loadedmetadata` yet yield 0, matching this component's fallback to the
 * first line rather than showing nothing while narration has already
 * started. `positionMs` past `totalMs` (e.g. during teach-back, after the
 * segment has already ended) clamps to the last line rather than going out
 * of bounds.
 */
export function activeCaptionLineIndex(
  lines: string[],
  positionMs: number,
  totalMs: number
): number {
  if (lines.length === 0) return -1;
  if (totalMs <= 0) return 0;

  const totalChars = lines.reduce((sum, line) => sum + line.length, 0);
  if (totalChars === 0) return 0;

  let cumulativeMs = 0;
  for (let i = 0; i < lines.length; i++) {
    cumulativeMs += (lines[i].length / totalChars) * totalMs;
    if (positionMs < cumulativeMs) return i;
  }
  return lines.length - 1;
}

/**
 * Which caption line is "active" at `positionMs`, given real server-measured
 * `start_ms`/`end_ms` windows (Story 4-29's `_split_into_caption_lines` guarantees
 * these are contiguous and ordered, with the last line's `end_ms` exactly equal to
 * the segment's measured audio duration). Exported for unit testing.
 *
 * Clamps to the first line before its `start_ms` (only reachable on an early render
 * tick before playback position updates) and to the last line once `positionMs`
 * reaches or exceeds its `end_ms` -- the same clamp behavior as the proportional
 * estimate below, for the same reasons (e.g. teach-back after the segment ends).
 */
export function activeCaptionLineIndexFromTimestamps(
  lines: CaptionLine[],
  positionMs: number
): number {
  if (lines.length === 0) return -1;
  for (let i = 0; i < lines.length; i++) {
    if (positionMs < lines[i].end_ms) return i;
  }
  return lines.length - 1;
}

export function CaptionOverlay({ script, captionLines }: CaptionOverlayProps) {
  const audioPositionMs = usePlayerStore((s) => s.audioPositionMs);
  const audioDurationMs = usePlayerStore((s) => s.audioDurationMs);

  const hasRealTimestamps = !!captionLines && captionLines.length > 0;

  // Only computed when the real-timestamp path isn't available -- this is the
  // pre-existing degraded-case behavior (Story 4-29 AC5), unchanged.
  const fallbackLines = useMemo(
    () => (!hasRealTimestamps && script ? splitScriptIntoCaptionLines(script) : []),
    [script, hasRealTimestamps]
  );

  const activeIndex = hasRealTimestamps
    ? activeCaptionLineIndexFromTimestamps(captionLines, audioPositionMs)
    : activeCaptionLineIndex(fallbackLines, audioPositionMs, audioDurationMs);

  // Render nothing when there is nothing to show -- mirrors SlideImage's own
  // "render nothing rather than a blank space-eating placeholder" pattern in
  // SlideRenderer.tsx.
  if (activeIndex === -1) return null;

  const activeText = hasRealTimestamps ? captionLines[activeIndex].text : fallbackLines[activeIndex];

  return (
    <div
      data-testid="caption-overlay"
      // Review fix (2026-08-17): this used to also carry `pointer-events-none`,
      // which blocks ALL mouse/wheel interaction including the wheel-driven
      // scroll `overflow-y-auto` provides, and lacked `data-lenis-prevent`
      // (SmoothScroll.tsx's global Lenis instance otherwise hijacks the wheel
      // event before it ever reaches this element's own scroll -- see the
      // sibling SlideRenderer.tsx for the same, already-fixed problem).
      // Verified live: a real narration segment clipped 390 of 616px (~63%)
      // of its text with NO way to read the rest. Kept here as a defensive
      // fallback now that lines are short -- should rarely if ever trigger.
      data-lenis-prevent
      className="absolute bottom-0 inset-x-0 z-10 max-h-[30%] overflow-y-auto overscroll-y-contain
                 bg-black/60 backdrop-blur-sm px-5 py-3"
    >
      <p
        key={activeIndex}
        className="text-neutral-100 text-sm leading-relaxed text-center max-w-3xl mx-auto"
      >
        {activeText}
      </p>
    </div>
  );
}
