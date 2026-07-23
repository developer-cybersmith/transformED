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
    <div className="flex-1 flex flex-col bg-primary-dark animate-pulse" data-testid="player-skeleton">
      <div className="h-1.5 bg-neutral-800 w-full" />
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6">
        <div className="w-48 h-6 rounded bg-neutral-800" />
        <div className="w-32 h-4 rounded bg-neutral-800" />
      </div>
      <div className="h-20 bg-[#07172C] border-t border-white/5" />
    </div>
  );
}

function LessonErrorState({ message }: { message?: string | null }) {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 text-center"
      data-testid="lesson-error"
    >
      <p className="text-neutral-400 mb-6">
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

function LessonGeneratingState() {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 text-center"
      data-testid="lesson-generating"
    >
      <div className="w-8 h-8 border-2 border-white/20 border-t-white rounded-full animate-spin mb-6" />
      <p className="text-neutral-400">This lesson is still generating. Hang tight...</p>
    </div>
  );
}

interface PlayerLoaderProps {
  lessonId: string;
}

export function PlayerLoader({ lessonId }: PlayerLoaderProps) {
  const { lesson, isLoading, error, status, serverError } = useLesson(lessonId);

  if (error) return <LessonErrorState />;
  if (isLoading) return <PlayerSkeleton />;
  // "running"/"queued" (still generating) is a normal state a direct-navigated
  // (bookmark/refresh/back-button) request can land on -- not an error.
  if (status === 'running' || status === 'queued') return <LessonGeneratingState />;
  if (status === 'failed') return <LessonErrorState message={serverError} />;
  if (!lesson) return <LessonErrorState />;
  return <Player lesson={lesson} />;
}
