import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { usePlayerStore } from '@/stores/player.machine';
import type { LessonPackage } from '@hie/shared/types/lesson';

// ── Fixture ─────────────────────────────────────────────────────────────────

function makeLesson(segmentCount = 3): LessonPackage {
  return {
    lesson_id: 'lesson_test_1',
    book_id: 'book_1',
    chapter_id: 'chap_1',
    created_at: '2026-06-26T00:00:00Z',
    metadata: {
      title: 'Test Lesson',
      subject: 'Testing',
      total_segments: segmentCount,
      estimated_duration_mins: 10,
      complexity_level: 'medium',
    },
    segments: Array.from({ length: segmentCount }, (_, i) => ({
      segment_id: `seg_${i}`,
      segment_index: i,
      title: `Segment ${i}`,
      summary: `Summary ${i}`,
      complexity: {
        level: 'medium' as const,
        cognitive_load: 'medium',
        abstraction_level: 'concrete',
        prerequisite_concepts: [],
        narration_style: 'explanatory',
        quiz_difficulty: 'medium',
        intervention_sensitivity: 0.5,
      },
      slides: [
        { slide_id: `sl_${i}_0`, title: `Slide ${i}-0`, bullets: ['Point A'], image_url: null, fallback_image_url: null },
        { slide_id: `sl_${i}_1`, title: `Slide ${i}-1`, bullets: ['Point B'], image_url: null, fallback_image_url: null },
      ],
      narration: {
        script: `Script for segment ${i}`,
        audio_url: `https://cdn.hie.ai/seg_${i}.mp3`,
        audio_provider: 'azure' as const,
        timestamps: [
          { slide_id: `sl_${i}_0`, start_ms: 0,     end_ms: 5000  },
          { slide_id: `sl_${i}_1`, start_ms: 5000,  end_ms: 10000 },
        ],
      },
      quiz: [{
        question_id: `q_${i}`,
        type: 'mcq' as const,
        question: `Question ${i}?`,
        options: ['A', 'B', 'C', 'D'],
        correct_index: 0,
        explanation: 'Because A.',
        difficulty: 'medium' as const,
      }],
      teachback_prompt: `Explain segment ${i} in your own words.`,
      jargon: [{ term: 'API', definition: 'Application Programming Interface' }],
      interventions: {
        distraction: ['msg1', 'msg2', 'msg3'],
        confusion: ['msg1', 'msg2', 'msg3'],
        fatigue: ['msg1', 'msg2', 'msg3'],
      },
    })),
    glossary: [],
  };
}

// Reset Zustand store before each test
beforeEach(() => {
  usePlayerStore.setState({
    status: 'IDLE',
    lesson: null,
    currentSegmentIndex: 0,
    currentSlideId: null,
    audioPositionMs: 0,
    tutorState: 'IDLE',
    quizFiredForSegment: new Set(),
    wsSendControl: null,
  });
  localStorage.clear();
});

// Guarantee any Storage.prototype spy is restored even if a test's own
// assertion throws before reaching its own mockRestore() call — otherwise a
// failing "does not throw" test permanently breaks localStorage for every
// test that runs after it in this file.
afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe('loadLesson', () => {
  it('initialises status to IDLE', () => {
    const lesson = makeLesson();
    usePlayerStore.getState().loadLesson(lesson);
    expect(usePlayerStore.getState().status).toBe('IDLE');
  });

  it('sets currentSegmentIndex to 0', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(0);
  });

  it('sets currentSlideId to the first timestamp slide_id', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_0');
  });

  it('clears quizFiredForSegment', () => {
    // Pre-populate to simulate a prior session
    usePlayerStore.setState({ quizFiredForSegment: new Set(['seg_0']) });
    usePlayerStore.getState().loadLesson(makeLesson());
    expect(usePlayerStore.getState().quizFiredForSegment.size).toBe(0);
  });

  it('resets audioPositionMs to 0', () => {
    usePlayerStore.setState({ audioPositionMs: 9999 });
    usePlayerStore.getState().loadLesson(makeLesson());
    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });
});

describe('play / pause', () => {
  it('IDLE → PLAYING on play()', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  it('PLAYING → PAUSED on pause()', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().pause();
    expect(usePlayerStore.getState().status).toBe('PAUSED');
  });

  it('PAUSED → PLAYING on play()', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().pause();
    usePlayerStore.getState().play();
    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  it('pause() is no-op when IDLE', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().pause();
    expect(usePlayerStore.getState().status).toBe('IDLE');
  });
});

describe('setCurrentSlide', () => {
  it('updates currentSlideId when slide changes', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().setCurrentSlide('sl_0_1');
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_1');
  });

  it('does NOT trigger a state change when slide_id is the same (no-op)', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    // currentSlideId starts as 'sl_0_0'
    const before = usePlayerStore.getState().currentSlideId;
    usePlayerStore.getState().setCurrentSlide('sl_0_0');
    // State reference should be unchanged
    expect(usePlayerStore.getState().currentSlideId).toBe(before);
  });

  it('stores slide_id as a string, never a number', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().setCurrentSlide('sl_0_1');
    expect(typeof usePlayerStore.getState().currentSlideId).toBe('string');
  });
});

describe('enterQuiz / exitQuiz / enterTeachBack / exitTeachBack', () => {
  it('PLAYING → QUIZ on enterQuiz()', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    expect(usePlayerStore.getState().status).toBe('QUIZ');
  });

  it('QUIZ → TEACH_BACK on exitQuiz()', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    usePlayerStore.getState().exitQuiz();
    expect(usePlayerStore.getState().status).toBe('TEACH_BACK');
  });

  it('TEACH_BACK → PLAYING on exitTeachBack()', () => {
    usePlayerStore.getState().loadLesson(makeLesson(5));
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    usePlayerStore.getState().exitQuiz();
    usePlayerStore.getState().exitTeachBack();
    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  it('exitTeachBack() resets tutorState to TEACHING when advancing to the next segment (S2-06 AC7)', () => {
    usePlayerStore.getState().loadLesson(makeLesson(5));
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    usePlayerStore.getState().exitQuiz();
    usePlayerStore.getState().exitTeachBack(); // not the last segment — advances
    expect(usePlayerStore.getState().tutorState).toBe('TEACHING');
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(1);
  });

  it('exitTeachBack() resets tutorState to TEACHING when resuming playback on the last segment (S2-06 AC7)', () => {
    usePlayerStore.getState().loadLesson(makeLesson(1)); // single-segment lesson — this is the last segment
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    usePlayerStore.getState().exitQuiz();
    usePlayerStore.getState().exitTeachBack();
    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(usePlayerStore.getState().tutorState).toBe('TEACHING');
  });

  it('enterQuiz() is no-op when not PLAYING', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    // status is IDLE — enterQuiz should not fire
    usePlayerStore.getState().enterQuiz();
    expect(usePlayerStore.getState().status).toBe('IDLE');
  });
});

describe('quizFiredForSegment — double-fire prevention', () => {
  it('adds segment_id to quizFiredForSegment on enterQuiz()', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    expect(usePlayerStore.getState().quizFiredForSegment.has('seg_0')).toBe(true);
  });

  it('does not fire quiz again for a segment already in quizFiredForSegment', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    // Pre-mark segment 0 as quizzed
    usePlayerStore.setState({ quizFiredForSegment: new Set(['seg_0']), status: 'PLAYING' });
    // enterQuiz() guard: status is PLAYING but seg_0 is already fired
    // Simulate the guard AudioTimeline uses:
    const { quizFiredForSegment, lesson, currentSegmentIndex } = usePlayerStore.getState();
    const segId = lesson!.segments[currentSegmentIndex].segment_id;
    const shouldFire = !quizFiredForSegment.has(segId);
    expect(shouldFire).toBe(false);
  });

  it('quiz NOT re-fired on seek backward (Set is not cleared by seek)', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().enterQuiz();
    // Simulate seek backward
    usePlayerStore.getState().requestSeek(0);
    expect(usePlayerStore.getState().quizFiredForSegment.has('seg_0')).toBe(true);
  });
});

describe('advanceSegment', () => {
  it('increments currentSegmentIndex', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().advanceSegment();
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(1);
  });

  it('sets currentSlideId to first slide of new segment', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().advanceSegment();
    expect(usePlayerStore.getState().currentSlideId).toBe('sl_1_0');
  });

  it('transitions to ENDED when advancing past last segment', () => {
    usePlayerStore.getState().loadLesson(makeLesson(2));
    usePlayerStore.getState().advanceSegment(); // 0 → 1
    usePlayerStore.getState().advanceSegment(); // 1 → END
    expect(usePlayerStore.getState().status).toBe('ENDED');
  });
});

describe('full 3-segment lesson traversal', () => {
  it('drives through the complete IDLE→PLAYING→QUIZ→TEACH_BACK×3→ENDED sequence', () => {
    const lesson = makeLesson(3);
    const store = usePlayerStore.getState();

    store.loadLesson(lesson);
    expect(usePlayerStore.getState().status).toBe('IDLE');

    store.play();
    expect(usePlayerStore.getState().status).toBe('PLAYING');

    // Segment 0
    store.enterQuiz();
    expect(usePlayerStore.getState().status).toBe('QUIZ');
    store.exitQuiz();
    expect(usePlayerStore.getState().status).toBe('TEACH_BACK');
    store.exitTeachBack(); // advances to seg 1, status → PLAYING
    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(1);

    // Segment 1
    store.enterQuiz();
    store.exitQuiz();
    store.exitTeachBack(); // advances to seg 2, status → PLAYING
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(2);

    // Segment 2 — last: exitTeachBack() resumes PLAYING on the last segment
    // (does not jump straight to ENDED) — remaining audio plays out and
    // AudioTimeline's handleEnded() calls endLesson() when it actually finishes.
    store.enterQuiz();
    store.exitQuiz();
    store.exitTeachBack();
    expect(usePlayerStore.getState().status).toBe('PLAYING');

    store.endLesson(); // simulates handleEnded() firing once the last segment's audio finishes
    expect(usePlayerStore.getState().status).toBe('ENDED');
  });
});

describe('updateAudioPosition', () => {
  it('updates audioPositionMs', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().updateAudioPosition(3500);
    expect(usePlayerStore.getState().audioPositionMs).toBe(3500);
  });
});

describe('setTutorState', () => {
  it('mirrors tutor FSM state from WebSocket', () => {
    usePlayerStore.getState().setTutorState('TEACHING');
    expect(usePlayerStore.getState().tutorState).toBe('TEACHING');
  });
});

describe('wsSendControl (S2-06)', () => {
  it('defaults to null', () => {
    expect(usePlayerStore.getState().wsSendControl).toBeNull();
  });

  it('setWsSendControl registers a callable function', () => {
    const fn = vi.fn();
    usePlayerStore.getState().setWsSendControl(fn);
    usePlayerStore.getState().wsSendControl?.({ type: 'segment_complete' });
    expect(fn).toHaveBeenCalledWith({ type: 'segment_complete' });
  });

  it('setWsSendControl(null) clears a previously registered function', () => {
    usePlayerStore.getState().setWsSendControl(vi.fn());
    usePlayerStore.getState().setWsSendControl(null);
    expect(usePlayerStore.getState().wsSendControl).toBeNull();
  });
});

// ── Session persistence (S2-05) ─────────────────────────────────────────────

const STORAGE_KEY = 'hie:session:lesson_test_1';

describe('saveProgress', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('writes the correct key and shape to localStorage', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.setState({ currentSegmentIndex: 1, audioPositionMs: 4200, quizFiredForSegment: new Set(['seg_0']) });

    usePlayerStore.getState().saveProgress();

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    expect(stored).toEqual({
      segmentIndex: 1,
      audioPositionMs: 4200,
      quizFiredForSegment: ['seg_0'],
      storedAt: 1_000_000,
    });
  });

  it('is a no-op when no lesson is loaded', () => {
    usePlayerStore.getState().saveProgress();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('throttles automatic saves triggered by updateAudioPosition — rapid calls within ~2s only write once', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    usePlayerStore.getState().loadLesson(makeLesson());

    usePlayerStore.getState().updateAudioPosition(1000);
    const firstWrite = localStorage.getItem(STORAGE_KEY);
    expect(firstWrite).not.toBeNull();

    vi.setSystemTime(1_000_500); // 500ms later — inside the throttle window
    usePlayerStore.getState().updateAudioPosition(1500);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).audioPositionMs).toBe(1000); // unchanged — throttled

    vi.setSystemTime(1_002_500); // 2.5s after the first write — outside the window
    usePlayerStore.getState().updateAudioPosition(2500);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).audioPositionMs).toBe(2500); // now written
  });

  it('pause() saves immediately, bypassing the throttle', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();
    usePlayerStore.getState().updateAudioPosition(1000); // primes the throttle window

    vi.setSystemTime(1_000_100); // 100ms later — still inside the throttle window
    usePlayerStore.setState({ audioPositionMs: 3000 });
    usePlayerStore.getState().pause();

    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).audioPositionMs).toBe(3000);
  });

  it('advanceSegment() saves immediately, bypassing the throttle', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().updateAudioPosition(1000); // primes the throttle window

    vi.setSystemTime(1_000_100);
    usePlayerStore.getState().advanceSegment();

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    expect(stored.segmentIndex).toBe(1);
  });

  it('enterQuiz() saves immediately — closing the tab mid-quiz must not lose the quizFiredForSegment update', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().play();

    usePlayerStore.getState().enterQuiz();

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    expect(stored.quizFiredForSegment).toContain('seg_0');
  });

  it('does not throw when localStorage.setItem throws (e.g. Safari private browsing / quota exceeded)', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    usePlayerStore.getState().loadLesson(makeLesson());

    expect(() => usePlayerStore.getState().saveProgress()).not.toThrow();

    spy.mockRestore();
  });
});

describe('restoreProgress', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('restores segmentIndex, audioPositionMs, quizFiredForSegment, and seeks via requestSeek', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 1,
      audioPositionMs: 6000, // within segment 1's second slide window (5000-10000)
      quizFiredForSegment: ['seg_0'],
      storedAt: Date.now(),
    }));
    usePlayerStore.getState().loadLesson(makeLesson());

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(true);
    const state = usePlayerStore.getState();
    expect(state.currentSegmentIndex).toBe(1);
    expect(state.audioPositionMs).toBe(6000);
    expect(state.seekRequestMs).toBe(6000);
    expect(state.quizFiredForSegment.has('seg_0')).toBe(true);
  });

  it('resolves currentSlideId correctly for the restored position (not left at segment 0\'s slide)', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 1,
      audioPositionMs: 6000, // segment 1's timestamps: sl_1_0 (0-5000), sl_1_1 (5000-10000)
      quizFiredForSegment: [],
      storedAt: Date.now(),
    }));
    usePlayerStore.getState().loadLesson(makeLesson());

    usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_1_1');
  });

  it('returns false and does nothing when no entry exists', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    const before = usePlayerStore.getState().currentSegmentIndex;

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(before);
  });

  it('returns false and removes the entry when the JSON is corrupted', () => {
    localStorage.setItem(STORAGE_KEY, 'not-valid-json{{{');
    usePlayerStore.getState().loadLesson(makeLesson());

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when fields have the wrong type', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 'not-a-number',
      audioPositionMs: 6000,
      quizFiredForSegment: [],
      storedAt: Date.now(),
    }));
    usePlayerStore.getState().loadLesson(makeLesson());

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when stored more than 24h ago', () => {
    vi.useFakeTimers();
    const now = 1_000_000_000;
    vi.setSystemTime(now);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 1,
      audioPositionMs: 6000,
      quizFiredForSegment: [],
      storedAt: now - (25 * 60 * 60 * 1000), // 25 hours ago
    }));
    usePlayerStore.getState().loadLesson(makeLesson());

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when segmentIndex is out of bounds for the currently loaded lesson', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 5, // lesson only has 3 segments (default makeLesson())
      audioPositionMs: 1000,
      quizFiredForSegment: [],
      storedAt: Date.now(),
    }));
    usePlayerStore.getState().loadLesson(makeLesson(3));

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when segmentIndex is not an integer (corrupted/tampered)', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 1.5,
      audioPositionMs: 1000,
      quizFiredForSegment: [],
      storedAt: Date.now(),
    }));
    usePlayerStore.getState().loadLesson(makeLesson(3));

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when audioPositionMs is negative', () => {
    usePlayerStore.getState().loadLesson(makeLesson(3));

    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segmentIndex: 0, audioPositionMs: -100, quizFiredForSegment: [], storedAt: Date.now(),
    }));

    expect(usePlayerStore.getState().restoreProgress('lesson_test_1')).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when audioPositionMs is non-finite (e.g. a 1e400-style JSON literal)', () => {
    usePlayerStore.getState().loadLesson(makeLesson(3));

    localStorage.setItem(
      STORAGE_KEY,
      '{"segmentIndex":0,"audioPositionMs":1e400,"quizFiredForSegment":[],"storedAt":' + Date.now() + '}'
    );

    expect(usePlayerStore.getState().restoreProgress('lesson_test_1')).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false and removes the entry when storedAt is non-finite (would otherwise defeat the 24h expiry check)', () => {
    // JSON.stringify would sanitize a literal Infinity to null before it ever
    // reaches storage — the real attack vector is a raw numeric literal like
    // 1e400, which is valid JSON syntax and JSON.parse converts to Infinity.
    localStorage.setItem(
      STORAGE_KEY,
      '{"segmentIndex":0,"audioPositionMs":1000,"quizFiredForSegment":[],"storedAt":1e400}'
    );
    usePlayerStore.getState().loadLesson(makeLesson(3));

    const restored = usePlayerStore.getState().restoreProgress('lesson_test_1');

    expect(restored).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('returns false without removing anything when lessonId does not match the currently loaded lesson', () => {
    localStorage.setItem('hie:session:other_lesson', JSON.stringify({
      segmentIndex: 0, audioPositionMs: 1000, quizFiredForSegment: [], storedAt: Date.now(),
    }));
    usePlayerStore.getState().loadLesson(makeLesson(3)); // loads lesson_test_1

    const restored = usePlayerStore.getState().restoreProgress('other_lesson');

    expect(restored).toBe(false);
    // The entry is for a different lesson than what's loaded — must not be deleted.
    expect(localStorage.getItem('hie:session:other_lesson')).not.toBeNull();
  });

  it('does not throw when localStorage.getItem throws (e.g. Safari private browsing / quota)', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    usePlayerStore.getState().loadLesson(makeLesson());

    expect(() => usePlayerStore.getState().restoreProgress('lesson_test_1')).not.toThrow();
    expect(usePlayerStore.getState().restoreProgress('lesson_test_1')).toBe(false);

    spy.mockRestore();
  });
});

describe('endLesson clears saved progress', () => {
  it('removes the localStorage entry so re-entering a completed lesson (e.g. "Study Again") starts fresh', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    usePlayerStore.getState().saveProgress();
    expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull();

    usePlayerStore.getState().endLesson();

    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('does not throw when localStorage.removeItem throws', () => {
    usePlayerStore.getState().loadLesson(makeLesson());
    const spy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });

    expect(() => usePlayerStore.getState().endLesson()).not.toThrow();

    spy.mockRestore();
  });
});
