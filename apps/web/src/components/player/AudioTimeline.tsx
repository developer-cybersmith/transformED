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
    setTutorState,
    wsSendControl,
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

  // Segment boundary: fire quiz exactly once per forward traversal. Notify the
  // backend tutor FSM (segment_complete) and optimistically mirror CHECKING_IN
  // locally in the same tick — see CheckingInTransition / Dev Notes "Timing
  // constraint" for why this can't wait for the backend's state_change echo.
  const segmentEnd = timestamps.at(-1)!.end_ms;
  if (ms >= segmentEnd && !quizFiredForSegment.has(segment.segment_id)) {
    setTutorState('CHECKING_IN');
    wsSendControl?.({ type: 'segment_complete' });
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
  const audioRetryCount = usePlayerStore((s) => s.audioRetryCount);

  const segment = lesson?.segments[currentSegmentIndex] ?? null;
  // Empty string is a real, reachable value now — a per-asset server-side
  // signing failure degrades just that one asset (Story 1-6/1-7), it doesn't
  // fail the whole lesson. There's nothing to play; don't attempt to.
  const hasAudio = Boolean(segment?.narration.audio_url);
  // Story 2-31 (backend) recovers the real script into a segment that still
  // has no playable audio -- narration.script alone changes nothing on screen
  // unless something drives processTimeUpdate for it (S2-33's virtual clock,
  // below). Distinct from hasAudio === false && !hasScript, which still has
  // nothing to advance the segment at all and keeps the immediate-advance path.
  const hasScript = Boolean(segment?.narration.script?.trim());

  // Status drives audio — audio never drives status (S1-01 invariant).
  // Also re-runs on currentSegmentIndex: replaying a previously-quizzed segment
  // (seek backward, let it reach its natural end) advances the segment via
  // handleEnded without any status transition — status is PLAYING before and
  // after. The <audio> element remounts on the new segment_id key, so without
  // this dependency the new element would never receive a .play() call and
  // playback would silently freeze despite the UI still showing "playing".
  // Also re-runs on audioRetryCount (S2-26 review fix): retryAudio() remounts
  // the <audio> element via the same key mechanism, but status/currentSegmentIndex
  // don't change on a same-segment retry -- without this dependency, the fresh
  // element would sit loaded-and-paused forever with no play() call, which is
  // worse than the original stall (no error, no progress, no recovery).
  useEffect(() => {
    if (hasAudio) {
      const audio = audioRef.current;
      if (!audio) return;
      if (status === 'PLAYING') {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
      return;
    }
    if (hasScript) {
      // Virtual clock (S2-33, separate effect below) owns ticking/advancing
      // this segment -- nothing to do here.
      return;
    }
    // Nothing will ever load and there's no script either, so 'ended'/'timeupdate'
    // can never fire for this segment (review fix) -- drive the same
    // advance/quiz logic handleEnded uses immediately instead of leaving the
    // lesson stuck here forever.
    if (status === 'PLAYING') handleEnded();
  }, [status, currentSegmentIndex, hasAudio, hasScript, audioRetryCount]);

  // Virtual playback clock (S2-33): a segment with a recovered narration script
  // but no playable audio (Story 2-31's degrade path) still needs *something*
  // to drive processTimeUpdate's slide-sync/quiz-boundary logic, or the segment
  // looks instantly "ended" -- this is exactly the "quiz fires at 0:00" symptom
  // Dev 1's handoff (docs/dev2-narration-playback-handoff.md) traced here.
  // Ticks only while PLAYING; the effect's own cleanup (on segment/status change)
  // is what stops it -- never calls handleEnded(), only processTimeUpdate(),
  // whose own boundary check already fires the quiz (AC-3: a second, independent
  // call to handleEnded() here would double-fire past an open quiz).
  useEffect(() => {
    if (hasAudio || !hasScript) return;
    if (status !== 'PLAYING') return;

    const interval = setInterval(() => {
      const current = usePlayerStore.getState().audioPositionMs;
      processTimeUpdate(current + 100);
    }, 100);

    return () => clearInterval(interval);
  }, [hasAudio, hasScript, status, currentSegmentIndex]);

  // Sets a real total duration for the scrubber even without audio metadata to
  // load from -- timestamps always exist here (Story 2-19's estimation),
  // independent of play/pause state, so this doesn't need to be gated on status.
  useEffect(() => {
    if (hasAudio || !hasScript || !segment) return;
    const { timestamps } = segment.narration;
    if (timestamps.length > 0) {
      usePlayerStore.getState().setAudioDuration(timestamps.at(-1)!.end_ms);
    }
  }, [hasAudio, hasScript, segment]);

  // Apply pending seek from the store then clear it. In virtual-clock mode
  // there's no real <audio> element to set .currentTime on -- absorb the seek
  // by applying it directly via processTimeUpdate instead (S2-33 AC-5).
  useEffect(() => {
    if (seekRequestMs === null) return;
    if (hasAudio) {
      const audio = audioRef.current;
      if (audio) {
        audio.currentTime = seekRequestMs / 1000;
      }
    } else if (hasScript) {
      processTimeUpdate(seekRequestMs);
    }
    usePlayerStore.getState().clearSeekRequest();
  }, [seekRequestMs, hasAudio, hasScript]);

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

  function handleWaiting() {
    usePlayerStore.getState().setBuffering(true);
  }

  function handlePlaying() {
    usePlayerStore.getState().setBuffering(false);
  }

  function handleCanPlay() {
    usePlayerStore.getState().setBuffering(false);
  }

  function handleError() {
    // Only a real mid-load/decode failure on a segment that DID have a src —
    // the hasAudio === false degrade path never renders a src attribute at
    // all, so this can't double-fire alongside that fallback.
    usePlayerStore.getState().setAudioError(true);
  }

  function handleEnded() {
    const {
      lesson: l,
      currentSegmentIndex: idx,
      quizFiredForSegment,
      endLesson,
      advanceSegment,
      setTutorState,
      wsSendControl,
      enterQuiz,
    } = usePlayerStore.getState();
    if (!l) return;
    const segment = l.segments[idx];
    const isLast = idx >= l.segments.length - 1;

    if (isLast) {
      // Last segment: end the lesson (quiz boundary detection handles quiz first if not yet fired)
      if (segment && !quizFiredForSegment.has(segment.segment_id)) {
        setTutorState('CHECKING_IN');
        wsSendControl?.({ type: 'segment_complete' });
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
        setTutorState('CHECKING_IN');
        wsSendControl?.({ type: 'segment_complete' });
        enterQuiz();
      }
    }
  }

  if (!segment) return null;

  return (
    // key includes audioRetryCount — forces remount on segment change AND on
    // retryAudio(), resetting src + currentTime so a failed load is re-attempted
    // from scratch rather than relying on the browser's own retry behavior.
    <audio
      key={`${segment.segment_id}-${audioRetryCount}`}
      ref={audioRef}
      src={hasAudio ? segment.narration.audio_url : undefined}
      preload="metadata"
      onLoadedMetadata={handleLoadedMetadata}
      onTimeUpdate={handleTimeUpdate}
      onEnded={handleEnded}
      onWaiting={handleWaiting}
      onPlaying={handlePlaying}
      onCanPlay={handleCanPlay}
      onError={handleError}
      aria-label={`Narration: ${segment.title}`}
      className="sr-only"
    />
  );
}
