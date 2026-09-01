'use client';

import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import posthog from 'posthog-js';
import { usePlayerStore } from '@/stores/player.machine';
import { FOCUS_RING } from '@/lib/a11y/focusRing';
import type { InterventionType } from '@hie/shared/types/ws';

// AC-6: fixed 30s auto-dismiss, independent of manual dismissal.
const AUTO_DISMISS_MS = 30_000;

const DEFAULT_VARIANT_STYLE = 'bg-white/95 border-neutral-300 text-neutral-800';

const VARIANT_STYLES: Record<InterventionType, string> = {
  distraction: 'bg-amber-50/95 border-amber-400 text-amber-900',
  confusion: 'bg-sky-50/95 border-sky-400 text-sky-900',
  fatigue: 'bg-neutral-50/95 border-neutral-300 text-neutral-800',
};

/**
 * Corner toast, not a full-screen overlay like CheckingInTransition — audio/
 * slide content behind it must stay fully visible and interactive (AC-5, AC-7).
 * Render-level TEACH_BACK guard (AC-3) requires an already-showing card to
 * vanish IMMEDIATELY on that transition — so, unlike CheckingInTransition,
 * there is deliberately no exit animation/AnimatePresence here: an animated
 * slide-out would contradict AC-3's "immediately" for that specific path.
 */
export function TutorInterventionCard() {
  const activeIntervention = usePlayerStore((s) => s.activeIntervention);
  const status = usePlayerStore((s) => s.status);
  const setActiveIntervention = usePlayerStore((s) => s.setActiveIntervention);
  const wsSendControl = usePlayerStore((s) => s.wsSendControl);
  // Story 2-54: same store Player.tsx reads lesson_id/session_id from --
  // trivially in scope here too, and needed to join intervention_received
  // back to a specific lesson/session in the funnel.
  const sessionId = usePlayerStore((s) => s.sessionId);
  const lesson = usePlayerStore((s) => s.lesson);

  const visible = activeIntervention !== null && status !== 'TEACH_BACK';

  // Bug fix (found live, 2026-08-12): dismissing only ever cleared local
  // React state -- it never told the server. The FSM's INTERVENING ->
  // TEACHING transition exists and is tested (state_machine/graph.py's
  // route_from_intervening) but had no caller anywhere, so a session's FIRST
  // intervention permanently stuck the tutor state in INTERVENING --
  // useAttentionMonitor.ts stops sending attention signals outside TEACHING,
  // so CES monitoring silently died for the rest of the session no matter
  // how long the student refocused. Fires on BOTH dismiss paths (auto and
  // manual) since either one means the student is done with this card.
  function dismiss() {
    setActiveIntervention(null);
    wsSendControl?.({ type: 'intervention_complete' });
  }

  // Derived purely from the payload's own content (not just `message`) so a
  // replacement with a different `type` but identical message text still
  // gets a distinct key -- forces a remount (fresh enter animation, no stale
  // variant styling left over from the previous card). A pure render-time
  // computation, not a ref/effect-driven counter.
  const renderKey = activeIntervention ? JSON.stringify(activeIntervention) : '';

  // Story 2-54: `visible` toggles false->true again for the SAME payload if
  // a card is showing when TEACH_BACK starts (activeIntervention isn't
  // cleared, only hidden) and then ends back to PLAYING -- guarded so a
  // given intervention only ever fires once, independent of that
  // visibility round-trip.
  //
  // Review fix (Edge Case Hunter): keyed on OBJECT REFERENCE equality
  // (`activeIntervention` itself), not `renderKey`'s content hash.
  // Intervention messages are pre-generated from a small fixed set per
  // lesson build (CLAUDE.md), so two genuinely DIFFERENT dispatches this
  // session (e.g. two "distraction" interventions) can easily share
  // identical type+message text -- a content-hash guard would wrongly
  // suppress the second, real intervention_received. A fresh dispatch is
  // always a new object reference even when its content is identical; the
  // SAME object surviving a TEACH_BACK round-trip is still `===` since it
  // is never replaced, only hidden -- so reference equality correctly
  // distinguishes the two cases the content hash could not.
  const firedInterventionRef = useRef<typeof activeIntervention>(null);
  useEffect(() => {
    if (!visible || !activeIntervention) return;
    if (firedInterventionRef.current === activeIntervention) return;
    firedInterventionRef.current = activeIntervention;
    posthog.capture('intervention_received', {
      intervention_type: activeIntervention.type,
      lesson_id: lesson?.lesson_id ?? null,
      session_id: sessionId || null,
    });
  }, [visible, activeIntervention, lesson, sessionId]);

  // Gated on `visible`, not just `activeIntervention` -- AC-6 measures 30s
  // "from when the card became visible". A payload that arrives while hidden
  // (e.g. during TEACH_BACK) must not burn its window before the student ever
  // sees it; the timer starts (or restarts) only once `visible` turns true.
  useEffect(() => {
    if (!visible || !activeIntervention) return;
    const current = activeIntervention;
    const timer = setTimeout(() => {
      // Guard against a stale timer firing after a newer intervention has
      // already replaced this one (same category of bug as
      // CheckingInTransition's stale-timer review fix). Reads wsSendControl
      // fresh from the store rather than closing over the render-time value,
      // matching the activeIntervention freshness check right above it.
      if (usePlayerStore.getState().activeIntervention === current) {
        setActiveIntervention(null);
        usePlayerStore.getState().wsSendControl?.({ type: 'intervention_complete' });
      }
    }, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [visible, activeIntervention, setActiveIntervention]);

  return (
    <>
      {/* Always mounted (never conditionally rendered/unmounted), unlike the
          visual toast below -- this is a genuine ARIA live-region content
          MUTATION on every new intervention rather than a fresh node
          insertion. Some screen reader/browser combinations only announce
          the former; a `key`-remounted node with pre-populated content can
          be silently skipped (review fix, S4-04). The visual toast keeps its
          own remount-per-intervention behavior for its enter animation and
          per-variant styling -- that's unrelated to whether the announcement
          fires and is left unchanged. */}
      <div role="status" aria-live="polite" className="sr-only" data-testid="tutor-intervention-announcer">
        {activeIntervention && visible ? activeIntervention.message : ''}
      </div>
      {activeIntervention && visible && (
        <motion.div
          key={renderKey}
          data-testid="tutor-intervention-card"
          data-variant={activeIntervention.type}
          initial={{ x: 40, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className={`absolute top-24 right-4 z-30 max-w-xs rounded-xl border-l-4 shadow-lg backdrop-blur-sm px-4 py-3 ${VARIANT_STYLES[activeIntervention.type] ?? DEFAULT_VARIANT_STYLE}`}
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium leading-snug">{activeIntervention.message}</p>
            <button
              type="button"
              onClick={dismiss}
              aria-label="Dismiss"
              className={`text-current/60 hover:text-current shrink-0 -mt-0.5 -mr-0.5 text-lg leading-none rounded ${FOCUS_RING}`}
            >
              &times;
            </button>
          </div>
        </motion.div>
      )}
    </>
  );
}
