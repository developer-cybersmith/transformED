'use client';

import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { usePlayerStore } from '@/stores/player.machine';
import type { InterventionType } from '@hie/shared/types/ws';

// AC-6: fixed 30s auto-dismiss, independent of manual dismissal.
const AUTO_DISMISS_MS = 30_000;

const VARIANT_STYLES: Record<InterventionType, string> = {
  distraction: 'bg-amber-50/95 border-amber-400 text-amber-900',
  confusion: 'bg-sky-50/95 border-sky-400 text-sky-900',
  fatigue: 'bg-neutral-50/95 border-neutral-300 text-neutral-800',
};

/**
 * Corner toast, not a full-screen overlay like CheckingInTransition — audio/
 * slide content behind it must stay fully visible and interactive (AC-5, AC-7).
 * Render-level TEACH_BACK guard (AC-3) means a card already showing vanishes
 * the instant status flips, with no need for a fresh WS message.
 */
export function TutorInterventionCard() {
  const activeIntervention = usePlayerStore((s) => s.activeIntervention);
  const status = usePlayerStore((s) => s.status);
  const setActiveIntervention = usePlayerStore((s) => s.setActiveIntervention);

  const visible = activeIntervention !== null && status !== 'TEACH_BACK';

  // Keyed on the payload reference so a replacement intervention (a new
  // setActiveIntervention call while one is already showing) restarts the
  // 30s window rather than being cut short by the previous one's timer.
  useEffect(() => {
    if (!activeIntervention) return;
    const current = activeIntervention;
    const timer = setTimeout(() => {
      // Guard against a stale timer firing after a newer intervention has
      // already replaced this one (same category of bug as
      // CheckingInTransition's stale-timer review fix).
      if (usePlayerStore.getState().activeIntervention === current) {
        setActiveIntervention(null);
      }
    }, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [activeIntervention, setActiveIntervention]);

  if (!visible) return null;

  return (
    <AnimatePresence>
      <motion.div
        key={activeIntervention.message}
        data-testid="tutor-intervention-card"
        data-variant={activeIntervention.type}
        initial={{ x: 40, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 40, opacity: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className={`absolute top-24 right-4 z-30 max-w-xs rounded-xl border-l-4 shadow-lg backdrop-blur-sm px-4 py-3 ${VARIANT_STYLES[activeIntervention.type]}`}
      >
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm font-medium leading-snug">{activeIntervention.message}</p>
          <button
            type="button"
            onClick={() => setActiveIntervention(null)}
            aria-label="Dismiss"
            className="text-current/60 hover:text-current shrink-0 -mt-0.5 -mr-0.5 text-lg leading-none"
          >
            &times;
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
