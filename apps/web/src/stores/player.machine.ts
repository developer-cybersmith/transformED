import { create } from 'zustand';
import type { LessonPackage } from '@hie/shared/types/lesson';
import type { TutorState } from '@hie/shared/types/ws';

export type PlayerStatus = 'IDLE' | 'PLAYING' | 'PAUSED' | 'QUIZ' | 'TEACH_BACK' | 'ENDED';

export interface PlayerStore {
  // ── State ──────────────────────────────────────────────────────────────────
  status: PlayerStatus;
  lesson: LessonPackage | null;
  /** Ephemeral session ID — generated on loadLesson; replaced by WS session_id in Sprint 2. */
  sessionId: string;
  currentSegmentIndex: number;
  /** String slide_id from NarrationTimestamp — NOT an array index. */
  currentSlideId: string | null;
  audioPositionMs: number;
  /** Total duration of the current segment's audio; 0 until metadata loads. */
  audioDurationMs: number;
  /** Non-null while a seek is pending; AudioTimeline applies it then clears it. */
  seekRequestMs: number | null;
  /** Playback rate multiplier; default 1.0. */
  playbackRate: number;
  tutorState: TutorState;
  /** segment_id values for segments where quiz has already fired this forward
   *  traversal. Not cleared on seek backward — quiz only re-fires on first
   *  forward crossing per session. */
  quizFiredForSegment: Set<string>;

  // ── Actions ────────────────────────────────────────────────────────────────
  /** Load a LessonPackage and reset all derived state to the beginning. */
  loadLesson: (pkg: LessonPackage) => void;
  /** Override the session ID once the WebSocket handshake provides a real one (Sprint 2). */
  setSessionId: (id: string) => void;
  play: () => void;
  pause: () => void;
  /** Queue a seek; AudioTimeline applies it to the audio element and clears it. */
  requestSeek: (ms: number) => void;
  clearSeekRequest: () => void;
  setAudioDuration: (ms: number) => void;
  setPlaybackRate: (rate: number) => void;
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
}

export const usePlayerStore = create<PlayerStore>((set, get) => ({
  // ── Initial state ──────────────────────────────────────────────────────────
  status: 'IDLE',
  lesson: null,
  sessionId: '',
  currentSegmentIndex: 0,
  currentSlideId: null,
  audioPositionMs: 0,
  audioDurationMs: 0,
  seekRequestMs: null,
  playbackRate: 1.0,
  tutorState: 'IDLE',
  quizFiredForSegment: new Set<string>(),

  // ── Actions ────────────────────────────────────────────────────────────────
  loadLesson: (pkg) => {
    const firstTimestamp = pkg.segments[0]?.narration.timestamps[0];
    set({
      status: 'IDLE',
      lesson: pkg,
      sessionId: crypto.randomUUID(),
      currentSegmentIndex: 0,
      currentSlideId: firstTimestamp?.slide_id ?? null,
      audioPositionMs: 0,
      audioDurationMs: 0,
      seekRequestMs: null,
      playbackRate: 1.0,
      tutorState: 'IDLE',
      quizFiredForSegment: new Set<string>(),
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

  requestSeek: (ms) => {
    // Update audioPositionMs immediately so the progress bar reflects the seek while paused.
    // Quiz boundary check in processTimeUpdate fires naturally on the next timeupdate tick.
    set({ seekRequestMs: ms, audioPositionMs: ms });
  },

  setSessionId: (id) => {
    set({ sessionId: id });
  },

  clearSeekRequest: () => {
    set({ seekRequestMs: null });
  },

  setAudioDuration: (ms) => {
    set({ audioDurationMs: ms });
  },

  setPlaybackRate: (rate) => {
    set({ playbackRate: rate });
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
      // Keep previous audioDurationMs until loadedmetadata fires on the new element —
      // avoids a flash where the seek bar is disabled between segments.
      seekRequestMs: null,
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
    if (get().status !== 'TEACH_BACK') return;
    const { lesson, currentSegmentIndex } = get();
    const isLastSegment = !lesson || currentSegmentIndex >= lesson.segments.length - 1;
    set({ status: 'PLAYING' });
    if (!isLastSegment) {
      get().advanceSegment();
    }
    // Last segment: audio resumes from its current position; handleEnded fires endLesson when it finishes
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
}));
