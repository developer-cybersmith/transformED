import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import type { NarrationTimestamp } from '@hie/shared/types/lesson';
import {
  binarySearchTimestamps,
  processTimeUpdate,
  handleAudioWaiting,
  handleAudioResume,
  handleAudioError,
} from '@/components/player/AudioTimeline';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

// ── 30-timestamp fixture (1 000 ms per slot) ────────────────────────────────

function make30Timestamps(): NarrationTimestamp[] {
  return Array.from({ length: 30 }, (_, i) => ({
    slide_id: `sl_${i}`,
    start_ms: i * 1000,
    end_ms: (i + 1) * 1000,
  }));
}

// ── Store reset helper ───────────────────────────────────────────────────────

beforeEach(() => {
  usePlayerStore.setState({
    status: 'IDLE',
    lesson: null,
    currentSegmentIndex: 0,
    currentSlideId: null,
    audioPositionMs: 0,
    tutorState: 'IDLE',
    quizFiredForSegment: new Set(),
  });
});

// ── binarySearchTimestamps ───────────────────────────────────────────────────

describe('binarySearchTimestamps — 30-timestamp fixture, 20 positions', () => {
  const ts = make30Timestamps();

  // Exact starts of each slot
  it('ms=0    → index 0   (sl_0)',  () => expect(binarySearchTimestamps(ts, 0)).toBe(0));
  it('ms=1000 → index 1   (sl_1)',  () => expect(binarySearchTimestamps(ts, 1000)).toBe(1));
  it('ms=5000 → index 5   (sl_5)',  () => expect(binarySearchTimestamps(ts, 5000)).toBe(5));
  it('ms=14000→ index 14  (sl_14)', () => expect(binarySearchTimestamps(ts, 14000)).toBe(14));
  it('ms=29000→ index 29  (sl_29)', () => expect(binarySearchTimestamps(ts, 29000)).toBe(29));

  // Mid-points inside a slot
  it('ms=500  → index 0   (still sl_0)',  () => expect(binarySearchTimestamps(ts, 500)).toBe(0));
  it('ms=1500 → index 1   (still sl_1)',  () => expect(binarySearchTimestamps(ts, 1500)).toBe(1));
  it('ms=7999 → index 7   (still sl_7)',  () => expect(binarySearchTimestamps(ts, 7999)).toBe(7));
  it('ms=10500→ index 10  (sl_10)',       () => expect(binarySearchTimestamps(ts, 10500)).toBe(10));
  it('ms=22750→ index 22  (sl_22)',       () => expect(binarySearchTimestamps(ts, 22750)).toBe(22));

  // Just-before-boundary stays on prior slide
  it('ms=999  → index 0   (sl_0, not sl_1)', () => expect(binarySearchTimestamps(ts, 999)).toBe(0));
  it('ms=1999 → index 1   (sl_1, not sl_2)', () => expect(binarySearchTimestamps(ts, 1999)).toBe(1));
  it('ms=8999 → index 8   (sl_8, not sl_9)', () => expect(binarySearchTimestamps(ts, 8999)).toBe(8));

  // Exact boundaries advance to new slide
  it('ms=2000 → index 2   (sl_2)', () => expect(binarySearchTimestamps(ts, 2000)).toBe(2));
  it('ms=9000 → index 9   (sl_9)', () => expect(binarySearchTimestamps(ts, 9000)).toBe(9));
  it('ms=20000→ index 20 (sl_20)', () => expect(binarySearchTimestamps(ts, 20000)).toBe(20));

  // Past-end clamps to last index
  it('ms=30000→ index 29 (last)',  () => expect(binarySearchTimestamps(ts, 30000)).toBe(29));
  it('ms=99999→ index 29 (last)',  () => expect(binarySearchTimestamps(ts, 99999)).toBe(29));

  // Verifies result is the INDEX, not the slide number (i.e. returns number type)
  it('returns a number', () => expect(typeof binarySearchTimestamps(ts, 5500)).toBe('number'));

  // Single-element array edge case
  it('single timestamp always returns 0', () => {
    const single = [{ slide_id: 'sl_only', start_ms: 0, end_ms: 5000 }];
    expect(binarySearchTimestamps(single, 2500)).toBe(0);
    expect(binarySearchTimestamps(single, 0)).toBe(0);
    expect(binarySearchTimestamps(single, 4999)).toBe(0);
  });
});

// ── processTimeUpdate — store integration ───────────────────────────────────

describe('processTimeUpdate — slide sync', () => {
  it('updates currentSlideId when audio enters a new slide', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING', currentSlideId: 'sl_0_0' });

    // mockLessonPackage seg_0: sl_0_0 at 0–15000ms, sl_0_1 at 15000–30000ms
    processTimeUpdate(16000); // into sl_0_1 range

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_1');
  });

  it('updates audioPositionMs', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING' });

    processTimeUpdate(8500);

    expect(usePlayerStore.getState().audioPositionMs).toBe(8500);
  });

  it('does NOT update slide when position stays in same slide', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING', currentSlideId: 'sl_0_0' });

    processTimeUpdate(3000); // still in sl_0_0 range (0–15000ms)

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });
});

describe('processTimeUpdate — segment boundary + quiz guard', () => {
  it('fires enterQuiz() when ms reaches segment end', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING' });

    // seg_0 ends at 30000ms
    processTimeUpdate(30000);

    expect(usePlayerStore.getState().status).toBe('QUIZ');
    expect(usePlayerStore.getState().quizFiredForSegment.has('seg_0')).toBe(true);
  });

  it('does NOT fire quiz again if already in quizFiredForSegment (seek backward scenario)', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({
      status: 'PLAYING',
      quizFiredForSegment: new Set(['seg_0']),
    });

    processTimeUpdate(30000); // boundary, but already fired

    // Status stays PLAYING — quiz was not re-triggered
    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });
});

describe('processTimeUpdate — status guards (no-op cases)', () => {
  it('is a no-op when status is QUIZ', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'QUIZ', audioPositionMs: 0 });

    processTimeUpdate(8000);

    // audioPositionMs should NOT change — entire function short-circuits
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });

  it('is a no-op when status is TEACH_BACK', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'TEACH_BACK', audioPositionMs: 0 });

    processTimeUpdate(8000);

    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });

  it('is a no-op when status is PAUSED', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PAUSED', audioPositionMs: 0 });

    processTimeUpdate(8000);

    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });

  it('is a no-op when lesson is null', () => {
    usePlayerStore.setState({ status: 'PLAYING', lesson: null, audioPositionMs: 0 });

    processTimeUpdate(5000);

    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });
});

// ── S1-11: buffer/error handler pure function tests ──────────────────────────

describe('handleAudioWaiting', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('4a: schedules setBuffering(true) after 2000ms', () => {
    vi.useFakeTimers();
    const ref = { current: null } as React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
    const setBuffering = vi.fn();

    handleAudioWaiting(ref, setBuffering);

    expect(setBuffering).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2000);
    expect(setBuffering).toHaveBeenCalledWith(true);
  });

  it('4b: onCanPlay before 2s cancels timer — setBuffering never called with true', () => {
    vi.useFakeTimers();
    const ref = { current: null } as React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
    const setBuffering = vi.fn();

    handleAudioWaiting(ref, setBuffering);
    vi.advanceTimersByTime(1000);
    handleAudioResume(ref, setBuffering); // cancel before 2s

    vi.advanceTimersByTime(2000);
    expect(setBuffering).not.toHaveBeenCalledWith(true);
    // setBuffering(false) was called by handleAudioResume
    expect(setBuffering).toHaveBeenCalledWith(false);
  });

  it('4c: onPlaying before 2s cancels timer — setBuffering(true) never fires', () => {
    vi.useFakeTimers();
    const ref = { current: null } as React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
    const setBuffering = vi.fn();

    handleAudioWaiting(ref, setBuffering);
    vi.advanceTimersByTime(500);
    handleAudioResume(ref, setBuffering); // onPlaying maps to handleAudioResume

    vi.advanceTimersByTime(2000);
    expect(setBuffering).not.toHaveBeenCalledWith(true);
  });

  it('4f: calling handleAudioWaiting twice only schedules one timer (idempotent)', () => {
    vi.useFakeTimers();
    const ref = { current: null } as React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
    const setBuffering = vi.fn();

    handleAudioWaiting(ref, setBuffering);
    handleAudioWaiting(ref, setBuffering); // second call is a no-op

    vi.advanceTimersByTime(2000);
    // setBuffering(true) called exactly once, not twice
    expect(setBuffering).toHaveBeenCalledTimes(1);
    expect(setBuffering).toHaveBeenCalledWith(true);
  });
});

describe('handleAudioError', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('4d: sets audioError to true and isBuffering to false', () => {
    const ref = { current: null } as React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
    const setBuffering = vi.fn();
    const setAudioError = vi.fn();

    handleAudioError(ref, setBuffering, setAudioError);

    expect(setAudioError).toHaveBeenCalledWith(true);
    expect(setBuffering).toHaveBeenCalledWith(false);
  });

  it('4e: clears pending buffer timer before setting audioError', () => {
    vi.useFakeTimers();
    const ref = { current: null } as React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
    const setBuffering = vi.fn();
    const setAudioError = vi.fn();

    handleAudioWaiting(ref, setBuffering); // schedule buffer timer
    expect(ref.current).not.toBeNull(); // timer was set

    handleAudioError(ref, setBuffering, setAudioError); // should cancel the timer
    expect(ref.current).toBeNull(); // timer was cleared

    vi.advanceTimersByTime(2000);
    // setBuffering(true) should NOT have been called — timer was cancelled
    expect(setBuffering).not.toHaveBeenCalledWith(true);
    expect(setAudioError).toHaveBeenCalledWith(true);
  });
});
