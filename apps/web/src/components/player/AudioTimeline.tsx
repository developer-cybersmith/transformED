'use client';

import { useRef, useEffect } from 'react';
import { usePlayerStore } from '@/stores/player.machine';

// Moved to lib/binarySearch.ts so stores/player.machine.ts (session-restore
// slide resolution) can use it without a component → store → component cycle.
// Re-exported here so existing imports from this module keep working.
import { binarySearchTimestamps } from '@/lib/binarySearch';
export { binarySearchTimestamps };

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
  // Malformed/partial pipeline output — nothing to sync the slide/quiz boundary to.
  if (timestamps.length === 0) return;

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
  const seekRequestMs = usePlayerStore((s) => s.seekRequestMs);
  const playbackRate = usePlayerStore((s) => s.playbackRate);

  const segment = lesson?.segments[currentSegmentIndex] ?? null;

  // Status drives audio — audio never drives status (S1-01 invariant).
  // Also re-runs on currentSegmentIndex: replaying a previously-quizzed segment
  // (seek backward, let it reach its natural end) advances the segment via
  // handleEnded without any status transition — status is PLAYING before and
  // after. The <audio> element remounts on the new segment_id key, so without
  // this dependency the new element would never receive a .play() call and
  // playback would silently freeze despite the UI still showing "playing".
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (status === 'PLAYING') {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }, [status, currentSegmentIndex]);

  // Apply pending seek from the store then clear it
  useEffect(() => {
    if (seekRequestMs === null) return;
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = seekRequestMs / 1000;
    }
    usePlayerStore.getState().clearSeekRequest();
  }, [seekRequestMs]);

  // Keep audio playback rate in sync
  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.playbackRate = playbackRate;
  }, [playbackRate]);

  function handleLoadedMetadata(e: React.SyntheticEvent<HTMLAudioElement>) {
    const durationMs = e.currentTarget.duration * 1000;
    usePlayerStore.getState().setAudioDuration(isFinite(durationMs) ? durationMs : 0);
    // Re-apply playback rate after src change resets it
    e.currentTarget.playbackRate = usePlayerStore.getState().playbackRate;
  }

  function handleTimeUpdate(e: React.SyntheticEvent<HTMLAudioElement>) {
    processTimeUpdate(e.currentTarget.currentTime * 1000);
  }

  function handleEnded() {
    const {
      lesson: l,
      currentSegmentIndex: idx,
      quizFiredForSegment,
      endLesson,
      advanceSegment,
      enterQuiz,
    } = usePlayerStore.getState();
    if (!l) return;
    const segment = l.segments[idx];
    const isLast = idx >= l.segments.length - 1;

    if (isLast) {
      // Last segment: end the lesson (quiz boundary detection handles quiz first if not yet fired)
      if (segment && !quizFiredForSegment.has(segment.segment_id)) {
        enterQuiz(); // audio ended before quiz fired (very short audio or tight timing)
      } else {
        endLesson();
      }
    } else {
      // Non-last segment: if quiz already fired (student sought back and replayed), advance
      if (segment && quizFiredForSegment.has(segment.segment_id)) {
        advanceSegment();
      }
      // If quiz hasn't fired yet, processTimeUpdate's boundary check should have caught it.
      // If the audio ended before hitting the boundary, fire the quiz now.
      else if (segment) {
        enterQuiz();
      }
    }
  }

  if (!segment) return null;

  return (
    // key={segment.segment_id} — forces remount on segment change, resetting src + currentTime
    <audio
      key={segment.segment_id}
      ref={audioRef}
      src={segment.narration.audio_url}
      preload="metadata"
      onLoadedMetadata={handleLoadedMetadata}
      onTimeUpdate={handleTimeUpdate}
      onEnded={handleEnded}
      aria-label={`Narration: ${segment.title}`}
      className="sr-only"
    />
  );
}
