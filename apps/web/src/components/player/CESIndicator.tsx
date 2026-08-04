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
 * Subtle corner badge -- never the raw CES float. Fixed 40x40px (AC-5's
 * literal size cap, in EITHER dimension). AC-4's qualitative label is
 * exposed via the native `title` tooltip (shown on hover/focus, and read by
 * screen readers) rather than permanently-visible text -- a visible text
 * label alongside the dot would exceed the 40px width cap with real words
 * like "Engaged" (review finding, resolved by user decision). Render-level
 * guard (AC-3): disappears immediately if `status` moves away from PLAYING,
 * without needing a fresh WS message, same pattern as
 * CheckingInTransition/TutorInterventionCard. Distinct corner from the tier
 * badge (top-3 left-3) and TutorInterventionCard (top-24 right-4).
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
      title={BAND_LABELS[band]}
      className={`absolute top-3 right-3 z-10 w-10 h-10 rounded-full flex items-center justify-center bg-black/40 backdrop-blur-sm`}
    >
      <span className={`w-2.5 h-2.5 rounded-full ${BAND_COLORS[band]}`} />
    </div>
  );
}
