'use client'

import dynamic from 'next/dynamic'
import type { LessonPackage } from '@transformed/shared/types/lesson'

// Dynamically import Player to avoid SSR issues (Audio API, canvas, MediaPipe)
const Player = dynamic(() => import('./Player').then((m) => m.Player), {
  ssr: false,
  loading: () => (
    <div className="flex h-screen items-center justify-center bg-slate-900">
      <div className="flex flex-col items-center gap-4 text-white">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
        <p className="text-sm text-slate-400">Loading lesson player…</p>
      </div>
    </div>
  ),
})

interface PlayerLoaderProps {
  lesson: LessonPackage
}

export function PlayerLoader({ lesson }: PlayerLoaderProps) {
  return <Player lesson={lesson} />
}
