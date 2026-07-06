import { create } from 'zustand';
import type { LessonPackage } from '@hie/shared/types/lesson';
import type { TutorState } from '@hie/shared/types/ws';
import { binarySearchTimestamps } from '@/lib/binarySearch';

const SAVE_THROTTLE_MS = 2000;
const MAX_STORED_AGE_MS = 24 * 60 * 60 * 1000;

// Last actual localStorage write, per loaded lesson — reset in loadLesson() so
// a stale timestamp from a previous, unrelated lesson session can never
// suppress the very first save of a new one.
let lastSavedAt = 0;

interface StoredProgress {
  segmentIndex: number;
  audioPositionMs: number;
  quizFiredForSegment: string[];
  storedAt: number;
}

function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage inaccessible — nothing more to do, the stale entry just lingers.
  }
}

function isStoredProgress(value: unknown): value is StoredProgress {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.segmentIndex === 'number' && Number.isInteger(v.segmentIndex) &&
    typeof v.audioPositionMs === 'number' && Number.isFinite(v.audioPositionMs) && v.audioPositionMs >= 0 &&
    typeof v.storedAt === 'number' && Number.isFinite(v.storedAt) &&
    Array.isArray(v.quizFiredForSegment) &&
    v.quizFiredForSegment.every((id) => typeof id === 'string')
  );
}

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
  /** Write current segment/position/quiz progress to localStorage, keyed by lesson_id. No-op with no lesson loaded. */
  saveProgress: () => void;
  /** Restore saved progress for lessonId (must be called after loadLesson). Returns true if a valid, fresh snapshot was applied. */
  restoreProgress: (lessonId: string) => boolean;
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
    lastSavedAt = 0;
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
      get().saveProgress();
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
    get().saveProgress();
  },

  enterQuiz: () => {
    const { status, lesson, currentSegmentIndex, quizFiredForSegment } = get();
    if (status !== 'PLAYING' || !lesson) return;
    const segment = lesson.segments[currentSegmentIndex];
    if (!segment) return;
    const next = new Set(quizFiredForSegment);
    next.add(segment.segment_id);
    set({ status: 'QUIZ', quizFiredForSegment: next });
    // Immediate, not throttled — audio is paused for the quiz so no further
    // updateAudioPosition ticks will fire to flush this update; closing the
    // tab here must not lose it (would re-fire an already-answered quiz).
    get().saveProgress();
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
    // Clear saved progress on completion — otherwise re-entering this lesson
    // (e.g. the session report's "Study Again" link) would silently resume
    // near the end instead of starting fresh.
    const { lesson } = get();
    if (typeof window !== 'undefined' && lesson) {
      try {
        localStorage.removeItem(`hie:session:${lesson.lesson_id}`);
      } catch {
        // Storage inaccessible (private browsing, disabled by policy) — not
        // fatal, the lesson still ends normally.
      }
    }
    set({ status: 'ENDED' });
  },

  setTutorState: (s) => {
    set({ tutorState: s });
  },

  updateAudioPosition: (ms) => {
    set({ audioPositionMs: ms });
    if (Date.now() - lastSavedAt >= SAVE_THROTTLE_MS) {
      get().saveProgress();
    }
  },

  saveProgress: () => {
    if (typeof window === 'undefined') return;
    const { lesson, currentSegmentIndex, audioPositionMs, quizFiredForSegment } = get();
    if (!lesson) return;
    const payload: StoredProgress = {
      segmentIndex: currentSegmentIndex,
      audioPositionMs,
      quizFiredForSegment: Array.from(quizFiredForSegment),
      storedAt: Date.now(),
    };
    try {
      localStorage.setItem(`hie:session:${lesson.lesson_id}`, JSON.stringify(payload));
      lastSavedAt = Date.now();
    } catch {
      // Storage inaccessible (Safari private browsing, quota exceeded) —
      // degrade gracefully, playback must not break because a save failed.
    }
  },

  restoreProgress: (lessonId) => {
    if (typeof window === 'undefined') return false;
    const key = `hie:session:${lessonId}`;

    let raw: string | null;
    try {
      raw = localStorage.getItem(key);
    } catch {
      return false;
    }
    if (!raw) return false;

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      safeRemove(key);
      return false;
    }

    if (!isStoredProgress(parsed)) {
      safeRemove(key);
      return false;
    }

    if (Date.now() - parsed.storedAt > MAX_STORED_AGE_MS) {
      safeRemove(key);
      return false;
    }

    const { lesson } = get();
    // Only meaningful when called after loadLesson() for this exact lesson —
    // a mismatch means the caller is out of order, not that this entry is
    // stale/corrupt, so it's left alone rather than deleted.
    if (!lesson || lesson.lesson_id !== lessonId) return false;

    if (parsed.segmentIndex < 0 || parsed.segmentIndex >= lesson.segments.length) {
      safeRemove(key);
      return false;
    }

    const segment = lesson.segments[parsed.segmentIndex];
    const { timestamps } = segment.narration;
    const slideId = timestamps.length > 0
      ? timestamps[binarySearchTimestamps(timestamps, parsed.audioPositionMs)].slide_id
      : null;

    set({
      currentSegmentIndex: parsed.segmentIndex,
      currentSlideId: slideId,
      quizFiredForSegment: new Set(parsed.quizFiredForSegment),
    });
    get().requestSeek(parsed.audioPositionMs);

    return true;
  },
}));
