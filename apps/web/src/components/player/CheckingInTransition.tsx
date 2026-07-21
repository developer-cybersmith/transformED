'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { usePlayerStore } from '@/stores/player.machine';

const TRANSITION_VISIBLE_MS = 500;

/**
 * tutorState's first real UI reader (S2-06). Edge-triggered by design, not a
 * persistent `tutorState === 'CHECKING_IN'` gate: this story doesn't send the
 * further flow events that would move the backend's FSM off CHECKING_IN on its
 * own, so a persistent gate would never auto-hide. Visibility is intentionally
 * independent of `status` — see Dev Notes "Two different 'state' concepts" in
 * docs/stories/2-6-segment-checkin.md.
 */
export function CheckingInTransition() {
  const tutorState = usePlayerStore((s) => s.tutorState);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (tutorState !== 'CHECKING_IN') return;
    // Deliberately synchronous: this must show the instant tutorState edges into
    // CHECKING_IN, with no one-tick flash of "not visible" first — a real browser
    // timer (external system) is what actually drives the auto-hide below.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVisible(true);
    const timer = setTimeout(() => setVisible(false), TRANSITION_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [tutorState]);

  if (!visible) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none bg-primary-dark/90 backdrop-blur-sm"
    >
      <p className="font-serif text-white text-lg">Checking in…</p>
    </motion.div>
  );
}
