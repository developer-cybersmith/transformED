'use client';

import { usePlayerStore } from '@/stores/player.machine';

type CesBand = 'low' | 'engaged' | 'focused';

const BAND_LABELS: Record<CesBand, string> = {
  low: 'Low',
  engaged: 'Engaged',
  focused: 'Focused',
};

const BAND_COLORS: Record<CesBand, string> = {
  low: 'bg-red-400',
  engaged: 'bg-amber-400',
  focused: 'bg-emerald-400',
};

function bandFor(score: number): CesBand {
  if (score < 0.4) return 'low';
  if (score <= 0.7) return 'engaged';
  return 'focused';
}

/**
 * Subtle corner dot -- never the raw CES float, only a qualitative label
 * (AC-4). Render-level guard (AC-3): disappears immediately if `status`
 * moves away from PLAYING, without needing a fresh WS message, same pattern
 * as CheckingInTransition/TutorInterventionCard. Distinct corner from the
 * tier badge (top-3 left-3) and TutorInterventionCard (top-24 right-4).
 */
export function CESIndicator() {
  const cesScore = usePlayerStore((s) => s.cesScore);
  const status = usePlayerStore((s) => s.status);

  if (cesScore === null || status !== 'PLAYING') return null;

  const band = bandFor(cesScore);

  return (
    <div
      data-testid="ces-indicator"
      data-band={band}
      className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-2 py-1 rounded-full bg-black/40 backdrop-blur-sm max-h-10"
    >
      <span className={`w-2 h-2 rounded-full ${BAND_COLORS[band]}`} />
      <span className="text-neutral-200 text-xs font-medium">{BAND_LABELS[band]}</span>
    </div>
  );
}
