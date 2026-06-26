'use client';

import { usePlayerStore } from '@/stores/player.machine';

function formatMs(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function PlayIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <polygon points="5,3 17,10 5,17" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <rect x="4" y="3" width="4" height="14" rx="1" />
      <rect x="12" y="3" width="4" height="14" rx="1" />
    </svg>
  );
}

export function PlayerControls() {
  const status = usePlayerStore((s) => s.status);
  const play = usePlayerStore((s) => s.play);
  const pause = usePlayerStore((s) => s.pause);
  const audioPositionMs = usePlayerStore((s) => s.audioPositionMs);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const totalSegments = lesson?.segments.length ?? 0;
  const isPlaying = status === 'PLAYING';
  const canControl = status === 'IDLE' || status === 'PLAYING' || status === 'PAUSED';

  return (
    <div className="flex items-center justify-between px-6 py-4 bg-[#0d0d14] border-t border-white/5 shrink-0">
      {/* Segment counter */}
      <span className="text-neutral-500 text-sm tabular-nums w-28">
        {totalSegments > 0 ? `Segment ${currentSegmentIndex + 1} / ${totalSegments}` : ''}
      </span>

      {/* Play / Pause */}
      <button
        onClick={isPlaying ? pause : play}
        disabled={!canControl}
        aria-label={isPlaying ? 'Pause' : 'Play'}
        className="w-12 h-12 rounded-full flex items-center justify-center text-white
                   bg-[var(--accent-primary)] hover:bg-[var(--accent-primary-hover)]
                   active:scale-95 transition-all duration-150
                   disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {isPlaying ? <PauseIcon /> : <PlayIcon />}
      </button>

      {/* Elapsed time */}
      <span className="text-neutral-500 text-sm tabular-nums w-28 text-right">
        {formatMs(audioPositionMs)}
      </span>
    </div>
  );
}
