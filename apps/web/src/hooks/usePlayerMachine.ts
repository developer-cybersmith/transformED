import { usePlayerStore } from '@/stores/player.machine';
import type { LessonPackage, Segment } from '@hie/shared/types/lesson';

/** Returns the current PlayerStatus. */
export const usePlayerStatus = () => usePlayerStore((s) => s.status);

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
/** Returns the loaded LessonPackage, or null if not yet loaded. */
export const useLesson = (): LessonPackage | null =>
  usePlayerStore((s) => s.lesson);

/** Returns the currently active Segment, or null. */
export const useCurrentSegment = (): Segment | null =>
  usePlayerStore((s) =>
    s.lesson ? s.lesson.segments[s.currentSegmentIndex] ?? null : null,
  );

/** Returns the current slide_id string, or null. */
export const useCurrentSlideId = (): string | null =>
  usePlayerStore((s) => s.currentSlideId);

/** Returns the current audio position in milliseconds. */
export const useAudioPositionMs = (): number =>
  usePlayerStore((s) => s.audioPositionMs);

/** Returns the tutor FSM state mirrored from Dev 4's WebSocket messages. */
export const useTutorState = () => usePlayerStore((s) => s.tutorState);

/** Returns whether the quiz has already fired for the given segment_id. */
export const useQuizFiredFor = (segmentId: string): boolean =>
  usePlayerStore((s) => s.quizFiredForSegment.has(segmentId));

/** Returns all player actions (stable references — safe to destructure). */
export const usePlayerActions = () =>
  usePlayerStore((s) => ({
    loadLesson: s.loadLesson,
    play: s.play,
    pause: s.pause,
    requestSeek: s.requestSeek,
    setPlaybackRate: s.setPlaybackRate,
    setCurrentSlide: s.setCurrentSlide,
    advanceSegment: s.advanceSegment,
    enterQuiz: s.enterQuiz,
    exitQuiz: s.exitQuiz,
    enterTeachBack: s.enterTeachBack,
    exitTeachBack: s.exitTeachBack,
    endLesson: s.endLesson,
    setTutorState: s.setTutorState,
    updateAudioPosition: s.updateAudioPosition,
  }));
