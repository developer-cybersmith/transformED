'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';
import { AudioTimeline } from './AudioTimeline';
import { SlideRenderer } from './SlideRenderer';
import { PlayerControls } from './PlayerControls';
import { QuizOverlay } from './QuizOverlay';
import { TeachBackModal } from './TeachBackModal';

interface PlayerProps {
  lesson: LessonPackage;
}

// Default export required by next/dynamic
export default function Player({ lesson }: PlayerProps) {
  const loadLesson = usePlayerStore((s) => s.loadLesson);
  const status = usePlayerStore((s) => s.status);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);
  const currentSlideId = usePlayerStore((s) => s.currentSlideId);

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

        {/* Lesson metadata shown before any slide is active */}
        {!currentSlideId && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6">
            <h2 className="text-xl font-semibold">{lesson.metadata.title}</h2>
            <p className="text-neutral-400 text-sm">
              {lesson.metadata.total_segments} segments · ~{lesson.metadata.estimated_duration_mins} min
            </p>
          </div>
        )}

        {/* Quiz overlay — mounts over slide area when status === 'QUIZ' */}
        {status === 'QUIZ' && segment && (
          <QuizOverlay questions={segment.quiz} />
        )}

        {/* Teach-back modal — mounts after quiz when status === 'TEACH_BACK' */}
        {status === 'TEACH_BACK' && segment && (
          <TeachBackModal
            prompt={segment.teachback_prompt}
            segmentTitle={segment.title}
          />
        )}

        {/* Lesson complete screen */}
        {status === 'ENDED' && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-6 p-6 bg-[#0a0a0f]/95 backdrop-blur-sm">
            <div className="text-4xl">🎓</div>
            <div className="text-center">
              <h2 className="text-white text-xl font-semibold mb-1">Lesson complete</h2>
              <p className="text-neutral-400 text-sm">{lesson.metadata.title}</p>
            </div>
            <div className="flex flex-col items-center gap-3">
              <Link
                href="/dashboard"
                className="px-6 py-2.5 rounded-full bg-[var(--accent-primary)] hover:bg-[var(--accent-primary-hover)]
                           text-white text-sm font-medium transition-colors"
              >
                Back to Dashboard
              </Link>
              <p className="text-neutral-600 text-xs">
                Session report available in Sprint 2
              </p>
            </div>
          </div>
        )}
      </div>

      <PlayerControls />
    </div>
  );
}
