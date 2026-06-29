'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { ArrowLeft, RefreshCw, Bug } from 'lucide-react';
import { useLesson } from '@/hooks/useLesson';
import type { LessonPackage } from '@hie/shared/types/lesson';

// ssr: false — Player uses Web Audio API and will load MediaPipe WASM in Sprint 3.
// This is the ONLY dynamic() call in the player stack; child components import normally.
const Player = dynamic(() => import('./Player'), {
  ssr: false,
  loading: () => <PlayerSkeleton />,
});

export function PlayerSkeleton() {
  return (
    <div className="flex-1 flex flex-col bg-[#0a0a0f] animate-pulse" data-testid="player-skeleton">
      <div className="h-1.5 bg-neutral-800 w-full" />
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6">
        {/* Pulsing slide placeholder */}
        <div className="w-full max-w-2xl aspect-video rounded-xl bg-neutral-800" />
        <div className="w-48 h-6 rounded bg-neutral-800 mt-4" />
        <div className="w-32 h-4 rounded bg-neutral-700" />
      </div>
      <div className="h-20 bg-neutral-900 border-t border-neutral-800" />
    </div>
  );
}

function LessonErrorState() {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 text-center"
      data-testid="lesson-error"
    >
      <p className="text-neutral-400 mb-6">
        This lesson could not be loaded. Please try again.
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

function LessonParseErrorState() {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 text-center"
      data-testid="lesson-parse-error"
    >
      <p className="text-neutral-300 text-lg font-semibold mb-2">
        Lesson data is corrupted
      </p>
      <p className="text-neutral-500 text-sm mb-8 max-w-md">
        The lesson package could not be read. This is unexpected — our team has been notified. You can try reloading or report the issue.
      </p>
      <div className="flex items-center gap-3">
        <button
          onClick={() => window.location.reload()}
          className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-primary)] rounded-full text-white text-sm font-medium hover:scale-105 transition-transform"
        >
          <RefreshCw className="w-4 h-4" />
          Reload Lesson
        </button>
        <a
          href="https://github.com/HIE-corp/hie/issues"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-5 py-2.5 bg-neutral-800 rounded-full text-neutral-300 text-sm font-medium hover:bg-neutral-700 transition-colors"
        >
          <Bug className="w-4 h-4" />
          Report a Bug
        </a>
      </div>
    </div>
  );
}

function isValidLessonPackage(lesson: unknown): lesson is LessonPackage {
  if (!lesson || typeof lesson !== 'object') return false;
  const l = lesson as Partial<LessonPackage>;
  return (
    typeof l.lesson_id === 'string' &&
    Array.isArray(l.segments) &&
    l.segments.length > 0 &&
    typeof l.metadata === 'object' &&
    l.metadata !== null &&
    typeof (l.metadata as LessonPackage['metadata']).title === 'string'
  );
}

interface PlayerLoaderProps {
  lessonId: string;
}

export function PlayerLoader({ lessonId }: PlayerLoaderProps) {
  const { lesson, isLoading, error } = useLesson(lessonId);

  if (error) return <LessonErrorState />;
  if (isLoading || !lesson) return <PlayerSkeleton />;
  if (!isValidLessonPackage(lesson)) return <LessonParseErrorState />;
  return <Player lesson={lesson} />;
}
