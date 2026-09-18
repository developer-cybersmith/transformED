'use client';

import { usePlayerStore } from '@/stores/player.machine';
import { FOCUS_RING } from '@/lib/a11y/focusRing';

// Story 2-65 / BR-10. Direct user feedback: the slide-transition auto-pause
// (Story 2-57/BR-5) previously surfaced only as a small, easy-to-miss pill in
// the bottom-right corner. Replaces it with a real popup modal, mounted under
// the exact same `status === 'PAUSED' && pauseReason === 'slide-transition'`
// condition the pill used -- reuses TeachBackModal/AskTutorPanel's own
// overlay-card visual pattern rather than inventing a new one.
//
// Deliberately no live countdown/timer of any kind, even though the existing
// DEFAULT_SLIDE_TRANSITION_PAUSE_MS auto-resume timer keeps running unchanged
// underneath this -- matches this codebase's established "never show a
// numeric countdown to the student" pattern (CaptionOverlay,
// VoiceTeachBackRecorder), not just the teach-back-specific CLAUDE.md rule it
// originates from.
export function SlideTransitionPauseModal() {
  const play = usePlayerStore((s) => s.play);
  const pauseForIntervention = usePlayerStore((s) => s.pauseForIntervention);
  const skipTransitionPauseForSegment = usePlayerStore((s) => s.skipTransitionPauseForSegment);
  const setSkipTransitionPauseForSegment = usePlayerStore((s) => s.setSkipTransitionPauseForSegment);

  return (
    <div
      data-testid="slide-transition-pause-modal"
      className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-white/80 backdrop-blur-sm"
    >
      <div className="w-full max-w-md bg-white border border-neutral-200 rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-neutral-100">
          <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
            New Slide
          </span>
          <p className="font-serif text-neutral-900 text-lg leading-relaxed">
            Take a moment to look it over, then continue whenever you&apos;re ready.
          </p>
        </div>

        <div className="px-6 py-4">
          <label className="flex items-center gap-2 text-sm text-neutral-600 select-none cursor-pointer">
            <input
              type="checkbox"
              checked={skipTransitionPauseForSegment}
              onChange={(e) => setSkipTransitionPauseForSegment(e.target.checked)}
              className="rounded border-neutral-300 text-[var(--accent-secondary)] focus:ring-[var(--accent-secondary)]"
            />
            Skip pause for this segment
          </label>
        </div>

        <div className="px-6 pb-6 flex justify-between items-center">
          <button
            type="button"
            onClick={pauseForIntervention}
            className={`text-neutral-500 hover:text-neutral-900 text-sm font-medium transition-colors rounded ${FOCUS_RING}`}
          >
            Ask Tutor
          </button>
          <button
            type="button"
            onClick={play}
            autoFocus
            className={`px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                       text-primary text-sm font-semibold transition-all ${FOCUS_RING}`}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
