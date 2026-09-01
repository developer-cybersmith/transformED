'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useLesson } from '@/hooks/useLesson';

// ssr: false — Player uses Web Audio API and will load MediaPipe WASM in Sprint 3.
// This is the ONLY dynamic() call in the player stack; child components import normally.
const Player = dynamic(() => import('./Player'), {
  ssr: false,
  loading: () => <PlayerSkeleton />,
});

function PlayerSkeleton() {
  return (
    <div className="flex-1 flex flex-col bg-white animate-pulse" data-testid="player-skeleton">
      <div className="h-1.5 bg-neutral-200 w-full" />
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6">
        <div className="w-48 h-6 rounded bg-neutral-200" />
        <div className="w-32 h-4 rounded bg-neutral-200" />
      </div>
      <div className="h-20 bg-white border-t border-neutral-200" />
    </div>
  );
}

function LessonErrorState({ message }: { message?: string | null }) {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 text-center"
      data-testid="lesson-error"
    >
      <p className="text-neutral-500 mb-6">
        {message || 'This lesson could not be loaded. Please try again.'}
      </p>
      <Link
        href="/dashboard"
        className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-primary)] rounded-full text-white text-sm font-medium hover:scale-105 transition-transform"
      >
        <ArrowLeft className="w-4 h-4" />
        Return to Dashboard
      </Link>
    </div>
  );
}

function LessonGeneratingState({ timedOut, onCheckAgain }: { timedOut: boolean; onCheckAgain: () => void }) {
  // S4-11 review finding: closing the poll's infinite-loop gap (SWR stops
  // calling refreshInterval once it returns 0) means this hook can no longer
  // learn on its own whether a still-generating lesson has finished --
  // without this branch, the plain spinner below would silently freeze
  // forever with no way to tell "still working" apart from "gave up
  // 3 hours ago". Mirrors UploadFlow.tsx's giveUpSlow() degradation.
  if (timedOut) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center" data-testid="lesson-generating-timeout">
        <p className="text-neutral-500 mb-6">
          This is taking longer than expected. Your lesson may still be generating — check again in a moment.
        </p>
        <button
          type="button"
          onClick={onCheckAgain}
          className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-primary)] rounded-full text-white text-sm font-medium hover:scale-105 transition-transform"
        >
          Check again
        </button>
      </div>
    );
  }

  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 text-center"
      data-testid="lesson-generating"
    >
      <div className="w-8 h-8 border-2 border-neutral-200 border-t-[var(--accent-secondary)] rounded-full animate-spin mb-6" />
      <p className="text-neutral-500">This lesson is still generating. Hang tight...</p>
    </div>
  );
}

interface PlayerLoaderProps {
  lessonId: string;
}

export function PlayerLoader({ lessonId }: PlayerLoaderProps) {
  const { lesson, isLoading, error, status, serverError, pollTimedOut, refetch } = useLesson(lessonId);

  // Status-derived states take priority over the generic SWR `error` (review
  // fix): SWR retains the last good data/status across a failed background
  // revalidation, so a single transient poll failure must not flash a lesson
  // that's still genuinely running/queued to the permanent error page.
  // "running"/"queued" (still generating) is a normal state a direct-navigated
  // (bookmark/refresh/back-button) request can land on -- not an error.
  if (status === 'running' || status === 'queued') {
    return <LessonGeneratingState timedOut={pollTimedOut} onCheckAgain={refetch} />;
  }
  if (status === 'failed') return <LessonErrorState message={serverError} />;
  // Gated on status === 'ready' (not just lesson truthiness, review fix) --
  // content is only ever populated atomically with status 'ready' by the
  // real backend, but this keeps that invariant enforced defensively too.
  // Keyed by lesson_id so a client-side navigation between two different lessons
  // (S1-08 useLesson refetch) fully remounts Player rather than reusing the same
  // instance — avoids useLessonSocket/loadLesson racing against a stale sessionId
  // left over from the previous lesson (S2-06 review finding).
  if (status === 'ready' && lesson) {
    return <Player key={lesson.lesson_id} lesson={lesson} onRefetchLesson={refetch} />;
  }
  if (error) return <LessonErrorState />;
  if (isLoading) return <PlayerSkeleton />;
  return <LessonErrorState />;
}
