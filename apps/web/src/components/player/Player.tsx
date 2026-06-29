'use client';

import { useEffect } from 'react';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';
import { AudioTimeline } from './AudioTimeline';
import { SlideRenderer } from './SlideRenderer';
import { PlayerControls } from './PlayerControls';

interface PlayerProps {
  lesson: LessonPackage;
}

function BufferingOverlay() {
  return (
    <div
      data-testid="buffering-overlay"
      aria-live="polite"
      aria-label="Audio buffering"
      className="absolute inset-0 flex items-center justify-center bg-black/40 pointer-events-none z-10"
    >
      <svg
        className="animate-spin w-10 h-10 text-white/70"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden
      >
        <circle
          className="opacity-25"
          cx="12" cy="12" r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
    </div>
  );
}

function AudioErrorNotification({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      data-testid="audio-error-notification"
      aria-live="polite"
      role="alert"
      className="flex items-center justify-between px-6 py-3 bg-red-900/60 border-t border-red-700/50 text-white text-sm shrink-0"
    >
      <span>Audio failed to load.</span>
      <button
        onClick={onRetry}
        className="ml-4 px-4 py-1.5 bg-white/10 hover:bg-white/20 rounded-full text-sm font-medium transition-colors"
      >
        Try Again
      </button>
    </div>
  );
}

// Default export required by next/dynamic
export default function Player({ lesson }: PlayerProps) {
  const loadLesson = usePlayerStore((s) => s.loadLesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);
  const currentSlideId = usePlayerStore((s) => s.currentSlideId);
  const isBuffering = usePlayerStore((s) => s.isBuffering);
  const audioError = usePlayerStore((s) => s.audioError);
  const retryAudio = usePlayerStore((s) => s.retryAudio);

  useEffect(() => {
    loadLesson(lesson);
  }, [lesson, loadLesson]);

  const segment = lesson.segments[currentSegmentIndex] ?? null;

  return (
    <div className="flex-1 flex flex-col bg-[#0a0a0f] text-white overflow-hidden">
      {/* AudioTimeline: hidden, drives audio playback + slide sync */}
      <AudioTimeline />

      {/* Slide area — all slides rendered simultaneously; only active is visible */}
      <div className="relative flex-1">
        {segment?.slides.map((slide) => (
          <SlideRenderer
            key={slide.slide_id}
            slide={slide}
            isActive={slide.slide_id === currentSlideId}
            jargon={segment.jargon}
          />
        ))}

        {/* Buffering spinner overlay — shown after 2s audio stall */}
        {isBuffering && <BufferingOverlay />}

        {/* Lesson metadata shown before any slide is active */}
        {!currentSlideId && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6">
            <h2 className="text-xl font-semibold">{lesson.metadata.title}</h2>
            <p className="text-neutral-400 text-sm">
              {lesson.metadata.total_segments} segments · ~{lesson.metadata.estimated_duration_mins} min
            </p>
          </div>
        )}
      </div>

      {/* Audio error notification — shown on audio load failure */}
      {audioError && <AudioErrorNotification onRetry={retryAudio} />}

      <PlayerControls />
    </div>
  );
}
