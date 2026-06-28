'use client';

import { useRef, useEffect } from 'react';
import type { NarrationTimestamp } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';

/**
 * Binary search: returns the index of the latest timestamp whose start_ms ≤ currentMs.
 * O(log n) — no linear scan.
 * Exported for unit testing.
 */
export function binarySearchTimestamps(
  timestamps: NarrationTimestamp[],
  currentMs: number,
): number {
  let lo = 0, hi = timestamps.length - 1, result = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (timestamps[mid].start_ms <= currentMs) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

/**
 * Core audio-tick handler. Reads Zustand store via getState() to avoid stale closures
 * in the onTimeUpdate callback (fires at ~30 Hz). Exported for unit testing.
 */
export function processTimeUpdate(ms: number): void {
  const {
    status,
    lesson,
    currentSegmentIndex,
    currentSlideId,
    quizFiredForSegment,
    updateAudioPosition,
    setCurrentSlide,
    enterQuiz,
  } = usePlayerStore.getState();

  if (!lesson) return;
  // Only process when actively playing — freeze during QUIZ, TEACH_BACK, PAUSED, IDLE, ENDED
  if (status !== 'PLAYING') return;

  const segment = lesson.segments[currentSegmentIndex];
  if (!segment) return;

  updateAudioPosition(ms);

  const { timestamps } = segment.narration;
  const idx = binarySearchTimestamps(timestamps, ms);
  const targetSlideId = timestamps[idx].slide_id;

  if (targetSlideId !== currentSlideId) {
    setCurrentSlide(targetSlideId);
  }

  // Segment boundary: fire quiz exactly once per forward traversal
  const segmentEnd = timestamps.at(-1)!.end_ms;
  if (ms >= segmentEnd && !quizFiredForSegment.has(segment.segment_id)) {
    enterQuiz();
  }
}

export function AudioTimeline() {
  const audioRef = useRef<HTMLAudioElement>(null);

  const status = usePlayerStore((s) => s.status);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const segment = lesson?.segments[currentSegmentIndex] ?? null;

  // Status drives audio — audio never drives status (S1-01 invariant)
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (status === 'PLAYING') {
      audio.play().catch(() => {});
    } else if (status === 'PAUSED') {
      audio.pause();
    }
  }, [status]);

  function handleTimeUpdate(e: React.SyntheticEvent<HTMLAudioElement>) {
    processTimeUpdate(e.currentTarget.currentTime * 1000);
  }

  function handleEnded() {
    const { lesson: l, currentSegmentIndex: idx, endLesson } = usePlayerStore.getState();
    if (!l) return;
    if (idx >= l.segments.length - 1) {
      endLesson();
    }
    // Non-last segments: quiz should have already fired via handleTimeUpdate boundary detection
  }

  if (!segment) return null;

  return (
    // key={segment.segment_id} — forces remount on segment change, resetting src + currentTime
    <audio
      key={segment.segment_id}
      ref={audioRef}
      src={segment.narration.audio_url}
      onTimeUpdate={handleTimeUpdate}
      onEnded={handleEnded}
      aria-label={`Narration: ${segment.title}`}
      className="sr-only"
    />
  );
}
