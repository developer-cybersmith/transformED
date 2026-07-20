'use client';

import { usePlayerStore } from '@/stores/player.machine';

const SPEED_OPTIONS = [0.75, 1.0, 1.25, 1.5, 2.0];

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

function SkipBackIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path d="M9 10l6-5v10L9 10z" />
      <rect x="4" y="5" width="2.5" height="10" rx="1" />
    </svg>
  );
}

function SkipForwardIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path d="M11 10l-6-5v10l6-5z" />
      <rect x="13.5" y="5" width="2.5" height="10" rx="1" />
    </svg>
  );
}

export function PlayerControls() {
  const status        = usePlayerStore((s) => s.status);
  const play          = usePlayerStore((s) => s.play);
  const pause         = usePlayerStore((s) => s.pause);
  const audioPositionMs  = usePlayerStore((s) => s.audioPositionMs);
  const audioDurationMs  = usePlayerStore((s) => s.audioDurationMs);
  const requestSeek      = usePlayerStore((s) => s.requestSeek);
  const playbackRate     = usePlayerStore((s) => s.playbackRate);
  const setPlaybackRate  = usePlayerStore((s) => s.setPlaybackRate);
  const lesson           = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const totalSegments = lesson?.segments.length ?? 0;
  const isPlaying  = status === 'PLAYING';
  const canControl = status === 'IDLE' || status === 'PLAYING' || status === 'PAUSED';
  const canSeek    = canControl && audioDurationMs > 0;

  const progressPct = audioDurationMs > 0
    ? (audioPositionMs / audioDurationMs) * 100
    : 0;

  function handleProgressClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!canSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    requestSeek(Math.round(ratio * audioDurationMs));
  }

  function handleSkip(deltaMs: number) {
    if (!canSeek) return;
    requestSeek(Math.max(0, Math.min(audioDurationMs, audioPositionMs + deltaMs)));
  }

  function cycleSpeed() {
    const idx = SPEED_OPTIONS.indexOf(playbackRate);
    const next = SPEED_OPTIONS[(idx + 1) % SPEED_OPTIONS.length];
    setPlaybackRate(next);
  }

  return (
    <div className="shrink-0 bg-[#07172C] border-t border-white/5">
      {/* Progress bar */}
      <div
        role="slider"
        aria-label="Seek"
        aria-valuenow={audioPositionMs}
        aria-valuemin={0}
        aria-valuemax={audioDurationMs}
        onClick={handleProgressClick}
        className={[
          'relative h-1 w-full group',
          canSeek ? 'cursor-pointer' : 'cursor-default',
        ].join(' ')}
      >
        {/* Track */}
        <div className="absolute inset-0 bg-white/10" />
        {/* Fill */}
        <div
          className="absolute inset-y-0 left-0 bg-[var(--accent-secondary)] transition-[width] duration-100"
          style={{ width: `${progressPct}%` }}
        />
        {/* Thumb — visible on hover */}
        {canSeek && (
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
            style={{ left: `${progressPct}%` }}
          />
        )}
      </div>

      {/* Controls row */}
      <div className="flex items-center gap-3 px-5 py-3">
        {/* Left: segment counter */}
        <span className="text-neutral-500 text-xs tabular-nums w-20 shrink-0">
          {totalSegments > 0 ? `Seg ${currentSegmentIndex + 1} / ${totalSegments}` : ''}
        </span>

        {/* Centre: skip back · play/pause · skip forward */}
        <div className="flex-1 flex items-center justify-center gap-4">
          <button
            onClick={() => handleSkip(-10_000)}
            disabled={!canSeek}
            aria-label="Skip back 10 seconds"
            title="−10 s"
            className="text-neutral-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <SkipBackIcon />
          </button>

          <button
            onClick={isPlaying ? pause : play}
            disabled={!canControl}
            aria-label={isPlaying ? 'Pause' : 'Play'}
            className="w-11 h-11 rounded-full flex items-center justify-center text-primary
                       bg-[var(--accent-secondary)] hover:brightness-105
                       active:scale-95 transition-all duration-150
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>

          <button
            onClick={() => handleSkip(10_000)}
            disabled={!canSeek}
            aria-label="Skip forward 10 seconds"
            title="+10 s"
            className="text-neutral-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <SkipForwardIcon />
          </button>
        </div>

        {/* Right: speed · time */}
        <div className="flex items-center gap-3 w-20 justify-end shrink-0">
          <button
            onClick={cycleSpeed}
            aria-label={`Playback speed ${playbackRate}×`}
            className="text-neutral-400 hover:text-white text-xs font-medium tabular-nums w-8 text-center transition-colors"
          >
            {playbackRate === 1.0 ? '1×' : `${playbackRate}×`}
          </button>
          <span className="text-neutral-500 text-xs tabular-nums">
            {formatMs(audioPositionMs)}
          </span>
        </div>
      </div>
    </div>
  );
}
