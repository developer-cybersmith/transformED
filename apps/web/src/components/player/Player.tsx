'use client';

import { useEffect } from 'react';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';
import { AudioTimeline } from './AudioTimeline';

interface PlayerProps {
  lesson: LessonPackage;
}

// Default export required by next/dynamic
export default function Player({ lesson }: PlayerProps) {
  const loadLesson = usePlayerStore((s) => s.loadLesson);

  useEffect(() => {
    loadLesson(lesson);
  }, [lesson, loadLesson]);

  return (
    <div className="flex-1 flex flex-col bg-[#0a0a0f] text-white">
      {/* AudioTimeline is hidden (sr-only) but drives all audio + slide sync */}
      <AudioTimeline />
      <div className="flex-1 flex flex-col items-center justify-center gap-3">
        <h2 className="text-xl font-semibold">{lesson.metadata.title}</h2>
        <p className="text-neutral-400 text-sm">
          {lesson.metadata.total_segments} segments · ~{lesson.metadata.estimated_duration_mins} min
        </p>
        <p className="text-neutral-700 text-xs mt-6">
          SlideRenderer · AvatarOverlay coming in S1-04 – S1-05
        </p>
      </div>
    </div>
  );
}
