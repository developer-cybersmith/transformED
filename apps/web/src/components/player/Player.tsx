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

// Default export required by next/dynamic
export default function Player({ lesson }: PlayerProps) {
  const loadLesson = usePlayerStore((s) => s.loadLesson);
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
      </div>

      <PlayerControls />
    </div>
  );
}
