import { describe, it, expect, beforeEach } from 'vitest';
import type { NarrationTimestamp } from '@hie/shared/types/lesson';
import { binarySearchTimestamps, processTimeUpdate } from '@/components/player/AudioTimeline';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

// ── 30-timestamp fixture (1 000 ms per slot) ─────────────────────────────────

function make30Timestamps(): NarrationTimestamp[] {
  return Array.from({ length: 30 }, (_, i) => ({
    slide_id: `sl_${i}`,
    start_ms: i * 1000,
    end_ms: (i + 1) * 1000,
  }));
}

// ── Store reset before each test ─────────────────────────────────────────────

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

// ── binarySearchTimestamps — exact slot starts ────────────────────────────────

describe('binarySearchTimestamps — exact slot starts', () => {
  const ts = make30Timestamps();
  it('ms=0    → index 0  (sl_0)',  () => expect(binarySearchTimestamps(ts, 0)).toBe(0));
  it('ms=1000 → index 1  (sl_1)',  () => expect(binarySearchTimestamps(ts, 1000)).toBe(1));
  it('ms=5000 → index 5  (sl_5)',  () => expect(binarySearchTimestamps(ts, 5000)).toBe(5));
  it('ms=14000→ index 14 (sl_14)', () => expect(binarySearchTimestamps(ts, 14000)).toBe(14));
  it('ms=29000→ index 29 (sl_29)', () => expect(binarySearchTimestamps(ts, 29000)).toBe(29));
});

describe('binarySearchTimestamps — mid-points stay on current slide', () => {
  const ts = make30Timestamps();
  it('ms=500  → index 0  (still sl_0)',  () => expect(binarySearchTimestamps(ts, 500)).toBe(0));
  it('ms=1500 → index 1  (still sl_1)',  () => expect(binarySearchTimestamps(ts, 1500)).toBe(1));
  it('ms=7999 → index 7  (still sl_7)',  () => expect(binarySearchTimestamps(ts, 7999)).toBe(7));
  it('ms=10500→ index 10 (sl_10)',       () => expect(binarySearchTimestamps(ts, 10500)).toBe(10));
  it('ms=22750→ index 22 (sl_22)',       () => expect(binarySearchTimestamps(ts, 22750)).toBe(22));
});

describe('binarySearchTimestamps — just-before-boundary stays on prior slide', () => {
  const ts = make30Timestamps();
  it('ms=999  → index 0  (sl_0, not sl_1)', () => expect(binarySearchTimestamps(ts, 999)).toBe(0));
  it('ms=1999 → index 1  (sl_1, not sl_2)', () => expect(binarySearchTimestamps(ts, 1999)).toBe(1));
  it('ms=8999 → index 8  (sl_8, not sl_9)', () => expect(binarySearchTimestamps(ts, 8999)).toBe(8));
});

describe('binarySearchTimestamps — exact boundary advances to new slide', () => {
  const ts = make30Timestamps();
  it('ms=2000 → index 2  (sl_2)',  () => expect(binarySearchTimestamps(ts, 2000)).toBe(2));
  it('ms=9000 → index 9  (sl_9)',  () => expect(binarySearchTimestamps(ts, 9000)).toBe(9));
  it('ms=20000→ index 20 (sl_20)', () => expect(binarySearchTimestamps(ts, 20000)).toBe(20));
});

describe('binarySearchTimestamps — past-end clamps to last index', () => {
  const ts = make30Timestamps();
  it('ms=30000→ index 29 (last)',  () => expect(binarySearchTimestamps(ts, 30000)).toBe(29));
  it('ms=99999→ index 29 (last)',  () => expect(binarySearchTimestamps(ts, 99999)).toBe(29));
  it('returns number type',        () => expect(typeof binarySearchTimestamps(ts, 5500)).toBe('number'));
});

describe('binarySearchTimestamps — single-element array', () => {
  it('always returns 0 regardless of position', () => {
    const single: NarrationTimestamp[] = [{ slide_id: 'sl_only', start_ms: 0, end_ms: 5000 }];
    expect(binarySearchTimestamps(single, 0)).toBe(0);
    expect(binarySearchTimestamps(single, 2500)).toBe(0);
    expect(binarySearchTimestamps(single, 4999)).toBe(0);
  });
});

// Patch 1+2: empty array and negative ms edge cases
describe('binarySearchTimestamps — boundary edge cases', () => {
  const ts = make30Timestamps();
  // Empty array: loop never runs, result stays at initialised 0.
  // Caller (processTimeUpdate) must guard against empty segment timestamps before calling.
  it('empty array returns 0', () => {
    expect(binarySearchTimestamps([], 5000)).toBe(0);
    expect(binarySearchTimestamps([], 0)).toBe(0);
  });
  // Negative ms: no timestamp satisfies start_ms <= negative value; result stays 0 (first slide).
  it('negative ms clamps to index 0', () => {
    expect(binarySearchTimestamps(ts, -1)).toBe(0);
    expect(binarySearchTimestamps(ts, -100)).toBe(0);
  });
});

// ── processTimeUpdate — slide sync integration ────────────────────────────────

describe('processTimeUpdate — slide sync', () => {
  it('updates currentSlideId when audio crosses into a new slide', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING', currentSlideId: 'sl_0_0' });

    // seg_0: sl_0_0 at 0–15000ms, sl_0_1 at 15000–30000ms
    processTimeUpdate(16000);

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_1');
  });

  it('updates audioPositionMs on every call', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING' });
    processTimeUpdate(8500);
    expect(usePlayerStore.getState().audioPositionMs).toBe(8500);
  });

  it('does NOT update slide when position stays inside same slide', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING', currentSlideId: 'sl_0_0' });

    processTimeUpdate(3000); // still in sl_0_0 range (0–15000ms)

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  // Patch 5: verify per-segment relative time — seg_1 has its own timestamps starting at 0ms
  it('updates currentSlideId correctly when currentSegmentIndex is 1', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 1, currentSlideId: 'sl_1_0' });

    // seg_1: sl_1_0 at 0–15000ms, sl_1_1 at 15000–30000ms
    processTimeUpdate(16000);

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_1_1');
  });
});

describe('processTimeUpdate — segment boundary + quiz guard', () => {
  it('enters QUIZ state when ms reaches segment end', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING' });

    // seg_0 ends at 30000ms (sl_0_1.end_ms)
    processTimeUpdate(30000);

    expect(usePlayerStore.getState().status).toBe('QUIZ');
    expect(usePlayerStore.getState().quizFiredForSegment.has('seg_0')).toBe(true);
  });

  it('does NOT re-fire quiz on seek to already-fired segment (seek-backward guard)', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({
      status: 'PLAYING',
      quizFiredForSegment: new Set(['seg_0']),
    });

    processTimeUpdate(30000); // boundary hit, but already fired

    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  // Patch 4: verify quiz fires and records correct segment_id for seg_1
  it('enters QUIZ state for seg_1 and records seg_1 in quizFiredForSegment', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 1 });

    // seg_1 ends at 30000ms (sl_1_1.end_ms)
    processTimeUpdate(30000);

    expect(usePlayerStore.getState().status).toBe('QUIZ');
    expect(usePlayerStore.getState().quizFiredForSegment.has('seg_1')).toBe(true);
    expect(usePlayerStore.getState().quizFiredForSegment.has('seg_0')).toBe(false);
  });
});

describe('processTimeUpdate — status no-ops', () => {
  // Patch 6: all no-op tests assert both audioPositionMs and currentSlideId are unchanged
  it('is a no-op when status is QUIZ', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'QUIZ', audioPositionMs: 0, currentSlideId: 'sl_0_0' });
    processTimeUpdate(8000);
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  it('is a no-op when status is TEACH_BACK', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'TEACH_BACK', audioPositionMs: 0, currentSlideId: 'sl_0_0' });
    processTimeUpdate(8000);
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  it('is a no-op when status is PAUSED', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'PAUSED', audioPositionMs: 0, currentSlideId: 'sl_0_0' });
    processTimeUpdate(8000);
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  // Patch 3: IDLE and ENDED are also implicit no-ops via the status !== 'PLAYING' guard
  it('is a no-op when status is IDLE', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'IDLE', audioPositionMs: 0, currentSlideId: 'sl_0_0' });
    processTimeUpdate(8000);
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  it('is a no-op when status is ENDED', () => {
    usePlayerStore.getState().loadLesson(mockLessonPackage);
    usePlayerStore.setState({ status: 'ENDED', audioPositionMs: 0, currentSlideId: 'sl_0_0' });
    processTimeUpdate(8000);
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  it('is a no-op when lesson is null', () => {
    usePlayerStore.setState({ status: 'PLAYING', lesson: null, audioPositionMs: 0 });
    processTimeUpdate(5000);
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
    expect(usePlayerStore.getState().currentSlideId).toBeNull();
  });
});
