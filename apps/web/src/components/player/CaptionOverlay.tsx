'use client';

import { useMemo } from 'react';
import { usePlayerStore } from '@/stores/player.machine';

interface CaptionOverlayProps {
  /** Current segment's full narration script. Pass `segment?.narration.script ?? null`. */
  script: string | null;
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
// IMPORTANT CONSTRAINT, unchanged from before: there is no word/sentence-level
// timing anywhere in this pipeline. `NarrationTimestamp` (packages/shared/
// types/lesson.ts) is per-SLIDE, not per-word, and the Sarvam TTS integration
// returns no word-level timestamps at all. A frame-perfect, word-highlighted
// sync (true YouTube auto-caption behaviour) is NOT achievable without that
// backend/TTS work -- a separate, larger follow-up, same as before.
//
// What this DOES do without any new data: split the script into short,
// subtitle-length lines and estimate each line's time window by allocating
// the segment's total known duration proportionally to each line's character
// count (a much closer proxy for spoken duration than a flat per-line split,
// since narration lines vary a lot in length). This is an approximation, not
// real sync -- pacing, pauses, and emphasis all shift the true timing -- but
// it tracks actual playback position, drifts back into alignment every
// segment boundary (never compounds across segments), and never requires
// scrolling to read a line.

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

export function CaptionOverlay({ script }: CaptionOverlayProps) {
  const audioPositionMs = usePlayerStore((s) => s.audioPositionMs);
  const audioDurationMs = usePlayerStore((s) => s.audioDurationMs);

  const lines = useMemo(() => (script ? splitScriptIntoCaptionLines(script) : []), [script]);
  const activeIndex = activeCaptionLineIndex(lines, audioPositionMs, audioDurationMs);

  // Render nothing when there is nothing to show -- mirrors SlideImage's own
  // "render nothing rather than a blank space-eating placeholder" pattern in
  // SlideRenderer.tsx.
  if (activeIndex === -1) return null;

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
        {lines[activeIndex]}
      </p>
    </div>
  );
}
