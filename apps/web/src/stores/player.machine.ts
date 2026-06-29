import { create } from 'zustand';
import type { LessonPackage } from '@hie/shared/types/lesson';
import type { TutorState } from '@hie/shared/types/ws';

export type PlayerStatus = 'IDLE' | 'PLAYING' | 'PAUSED' | 'QUIZ' | 'TEACH_BACK' | 'ENDED';

export interface PlayerStore {
  // ── State ──────────────────────────────────────────────────────────────────
  status: PlayerStatus;
  lesson: LessonPackage | null;
  currentSegmentIndex: number;
  /** String slide_id from NarrationTimestamp — NOT an array index. */
  currentSlideId: string | null;
  audioPositionMs: number;
  tutorState: TutorState;
  /** segment_id values for segments where quiz has already fired this forward
   *  traversal. Not cleared on seek backward — quiz only re-fires on first
   *  forward crossing per session. */
  quizFiredForSegment: Set<string>;
  isBuffering: boolean;
  audioError: boolean;
  /** Incremented by retryAudio() to force <audio> remount via key prop change. */
  audioRetryCount: number;

  // ── Actions ────────────────────────────────────────────────────────────────
  /** Load a LessonPackage and reset all derived state to the beginning. */
  loadLesson: (pkg: LessonPackage) => void;
  play: () => void;
  pause: () => void;
  /** Seek audio to a position in ms; does NOT clear quizFiredForSegment. */
  seek: (ms: number) => void;
  /** Called by AudioTimeline on every timeUpdate; no-op if slide hasn't changed. */
  setCurrentSlide: (slideId: string) => void;
  /** Move to the next segment; calls endLesson() if already on the last one. */
  advanceSegment: () => void;
  /** Transition PLAYING → QUIZ and record segment as quizzed. */
  enterQuiz: () => void;
  /** Transition QUIZ → TEACH_BACK. */
  exitQuiz: () => void;
  /** Transition TEACH_BACK → PLAYING; advances to next segment. */
  enterTeachBack: () => void;
  exitTeachBack: () => void;
  endLesson: () => void;
  setTutorState: (s: TutorState) => void;
  updateAudioPosition: (ms: number) => void;
  setBuffering: (b: boolean) => void;
  setAudioError: (b: boolean) => void;
  /** Clears audioError and increments audioRetryCount to force <audio> remount. */
  retryAudio: () => void;
}

export const usePlayerStore = create<PlayerStore>((set, get) => ({
  // ── Initial state ──────────────────────────────────────────────────────────
  status: 'IDLE',
  lesson: null,
  currentSegmentIndex: 0,
  currentSlideId: null,
  audioPositionMs: 0,
  tutorState: 'IDLE',
  quizFiredForSegment: new Set<string>(),
  isBuffering: false,
  audioError: false,
  audioRetryCount: 0,

  // ── Actions ────────────────────────────────────────────────────────────────
  loadLesson: (pkg) => {
    const firstTimestamp = pkg.segments[0]?.narration.timestamps[0];
    set({
      status: 'IDLE',
      lesson: pkg,
      currentSegmentIndex: 0,
      currentSlideId: firstTimestamp?.slide_id ?? null,
      audioPositionMs: 0,
      tutorState: 'IDLE',
      quizFiredForSegment: new Set<string>(),
      isBuffering: false,
      audioError: false,
      audioRetryCount: 0,
    });
  },

  play: () => {
    const { status } = get();
    if (status === 'IDLE' || status === 'PAUSED') {
      set({ status: 'PLAYING' });
    }
  },

  pause: () => {
    if (get().status === 'PLAYING') {
      set({ status: 'PAUSED' });
    }
  },

  seek: (ms) => {
    set({ audioPositionMs: ms });
  },

  setCurrentSlide: (slideId) => {
    if (get().currentSlideId !== slideId) {
      set({ currentSlideId: slideId });
    }
  },

  advanceSegment: () => {
    const { lesson, currentSegmentIndex } = get();
    if (!lesson) return;
    const nextIndex = currentSegmentIndex + 1;
    if (nextIndex >= lesson.segments.length) {
      get().endLesson();
      return;
    }
    const firstTimestamp = lesson.segments[nextIndex].narration.timestamps[0];
    set({
      currentSegmentIndex: nextIndex,
      currentSlideId: firstTimestamp?.slide_id ?? null,
      audioPositionMs: 0,
      audioError: false,
    });
  },

  enterQuiz: () => {
    const { status, lesson, currentSegmentIndex, quizFiredForSegment } = get();
    if (status !== 'PLAYING' || !lesson) return;
    const segment = lesson.segments[currentSegmentIndex];
    if (!segment) return;
    const next = new Set(quizFiredForSegment);
    next.add(segment.segment_id);
    set({ status: 'QUIZ', quizFiredForSegment: next });
  },

  exitQuiz: () => {
    if (get().status === 'QUIZ') {
      set({ status: 'TEACH_BACK' });
    }
  },

  enterTeachBack: () => {
    if (get().status === 'QUIZ') {
      set({ status: 'TEACH_BACK' });
    }
  },

  exitTeachBack: () => {
    if (get().status === 'TEACH_BACK') {
      set({ status: 'PLAYING' });
      get().advanceSegment();
    }
  },

  endLesson: () => {
    set({ status: 'ENDED' });
  },

  setTutorState: (s) => {
    set({ tutorState: s });
  },

  updateAudioPosition: (ms) => {
    set({ audioPositionMs: ms });
  },

  setBuffering: (b) => {
    set({ isBuffering: b });
  },

  setAudioError: (b) => {
    set({ audioError: b });
  },

  retryAudio: () => {
    set((state) => ({ audioError: false, isBuffering: false, audioRetryCount: state.audioRetryCount + 1 }));
  },
}));
