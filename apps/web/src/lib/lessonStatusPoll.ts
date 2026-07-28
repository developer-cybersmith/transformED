import type { LessonStatusResponse } from '@/services/upload.service';

// S2-27: shared between useLibrary/useDashboard so a lesson that finishes
// generating while either page is open actually shows up without a manual
// refresh/navigation (SWR only refetches on remount/tab-refocus by default).
export const LESSON_STATUS_POLL_INTERVAL_MS = 8000;

export function isLessonProcessing(lesson: Pick<LessonStatusResponse, 'status'> | null | undefined): boolean {
  return lesson != null && (lesson.status === 'queued' || lesson.status === 'running');
}
