'use client'

import { useRef } from 'react'
import { Play, Pause, SkipBack, SkipForward } from 'lucide-react'
import type { PlayerState } from './player.machine'

interface AudioTimelineProps {
  playerState: PlayerState
  currentTimeMs: number
  durationMs: number
  onPlay: () => void
  onPause: () => void
  onSeek: (ms: number) => void
  onNext: () => void
  onPrev: () => void
  segmentIndex: number
  totalSegments: number
}

function formatTime(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return `${min}:${sec.toString().padStart(2, '0')}`
}

export function AudioTimeline({
  playerState,
  currentTimeMs,
  durationMs,
  onPlay,
  onPause,
  onSeek,
  onNext,
  onPrev,
  segmentIndex,
  totalSegments,
}: AudioTimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null)

  const progress = durationMs > 0 ? (currentTimeMs / durationMs) * 100 : 0
  const isPlaying = playerState === 'PLAYING'

  function handleTrackClick(e: React.MouseEvent<HTMLDivElement>) {
    const track = trackRef.current
    if (!track || durationMs === 0) return
    const rect = track.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    onSeek(ratio * durationMs)
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-slate-700 bg-slate-900 px-6 py-4">
      {/* Progress track */}
      <div
        ref={trackRef}
        onClick={handleTrackClick}
        role="slider"
        aria-label="Seek"
        aria-valuenow={currentTimeMs}
        aria-valuemin={0}
        aria-valuemax={durationMs}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') onSeek(Math.min(durationMs, currentTimeMs + 5000))
          if (e.key === 'ArrowLeft') onSeek(Math.max(0, currentTimeMs - 5000))
        }}
        className="group relative h-2 w-full cursor-pointer overflow-hidden rounded-full bg-slate-700"
      >
        <div
          className="absolute left-0 top-0 h-full rounded-full bg-primary-500 transition-[width] duration-100"
          style={{ width: `${Math.min(100, progress)}%` }}
        />
        {/* Thumb indicator */}
        <div
          className="absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full border-2 border-primary-500 bg-white opacity-0 shadow transition-opacity group-hover:opacity-100"
          style={{ left: `calc(${Math.min(100, progress)}% - 7px)` }}
        />
      </div>

      {/* Controls row */}
      <div className="flex items-center justify-between">
        {/* Time */}
        <span className="min-w-[80px] text-xs tabular-nums text-slate-400">
          {formatTime(currentTimeMs)} / {formatTime(durationMs)}
        </span>

        {/* Playback buttons */}
        <div className="flex items-center gap-4">
          <button
            onClick={onPrev}
            disabled={segmentIndex === 0}
            className="rounded p-1 text-slate-400 hover:text-white disabled:opacity-30 transition-colors"
            aria-label="Previous segment"
          >
            <SkipBack className="h-5 w-5" />
          </button>

          <button
            onClick={isPlaying ? onPause : onPlay}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-600 text-white shadow-md hover:bg-primary-700 transition-colors"
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? (
              <Pause className="h-5 w-5" />
            ) : (
              <Play className="ml-0.5 h-5 w-5" />
            )}
          </button>

          <button
            onClick={onNext}
            disabled={segmentIndex >= totalSegments - 1}
            className="rounded p-1 text-slate-400 hover:text-white disabled:opacity-30 transition-colors"
            aria-label="Next segment"
          >
            <SkipForward className="h-5 w-5" />
          </button>
        </div>

        {/* Segment counter */}
        <span className="min-w-[80px] text-right text-xs text-slate-400">
          Segment {segmentIndex + 1}/{totalSegments}
        </span>
      </div>
    </div>
  )
}
