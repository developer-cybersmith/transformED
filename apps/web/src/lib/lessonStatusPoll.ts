import type { LessonStatusResponse } from '@/services/upload.service';

// S2-27: shared between useLibrary/useDashboard so a lesson that finishes
// generating while either page is open actually shows up without a manual
// refresh/navigation (SWR only refetches on remount/tab-refocus by default).
export const LESSON_STATUS_POLL_INTERVAL_MS = 8000;

// Review fix: without a ceiling, a genuinely-stuck backend job (separately
// tracked as a Dev 1 backend/infra question, not something this story fixes)
// would poll every LESSON_STATUS_POLL_INTERVAL_MS indefinitely for as long as
// the tab stays open. Mirrors UploadFlow.tsx's own MAX_POLL_ATTEMPTS backstop
// (~20 minutes) for the identical underlying risk.
export const MAX_POLL_DURATION_MS = 20 * 60 * 1000;

export function isLessonProcessing(lesson: Pick<LessonStatusResponse, 'status'> | null | undefined): boolean {
  return lesson != null && (lesson.status === 'queued' || lesson.status === 'running');
}

/**
 * Tracks how long polling has been continuously active (via a ref supplied by
 * the caller) and returns the poll interval only while both something is
 * still processing AND the ceiling hasn't been reached. The ref resets
 * whenever nothing is processing, so a later, separate lesson starts its own
 * fresh window rather than inheriting an already-expired one.
 */
export function nextPollInterval(isProcessing: boolean, startedAtRef: { current: number | null }): number {
  if (!isProcessing) {
    startedAtRef.current = null;
    return 0;
  }
  if (startedAtRef.current === null) {
    startedAtRef.current = Date.now();
  }
  const elapsed = Date.now() - startedAtRef.current;
  return elapsed < MAX_POLL_DURATION_MS ? LESSON_STATUS_POLL_INTERVAL_MS : 0;
}
