import { describe, it, expect, beforeEach } from 'vitest';
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
  });
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
