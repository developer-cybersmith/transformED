'use client';

import { useState } from 'react';
import { usePlayerStore } from '@/stores/player.machine';
import { submitTutorQuestion } from '@/lib/assessment';
import { FOCUS_RING } from '@/lib/a11y/focusRing';

// Story 2-57 (BR-5): mounted whenever pauseReason === 'intervention' — see
// Player.tsx. Capture-and-log only (D149) — there is no live AI Q&A backend
// yet, confirmed with the user 2026-09-03. This panel never claims to answer
// the question; it only confirms it was recorded.
export function AskTutorPanel() {
  const play = usePlayerStore((s) => s.play);
  const sessionId = usePlayerStore((s) => s.sessionId);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);
  const audioPositionMs = usePlayerStore((s) => s.audioPositionMs);

  const [text, setText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const segment = lesson?.segments[currentSegmentIndex];

  async function handleSubmit() {
    if (!text.trim() || !lesson || !segment || !sessionId) return;

    setIsSubmitting(true);
    try {
      await submitTutorQuestion({
        session_id: sessionId,
        segment_id: segment.segment_id,
        question_text: text.trim(),
        audio_position_ms: audioPositionMs,
      });
      setSubmitted(true);
    } catch {
      // API unavailable — don't strand the student behind a form that can't
      // submit; let them resume, same degrade-gracefully convention as
      // TeachBackModal's own catch branch.
      play();
    } finally {
      setIsSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div
        data-testid="ask-tutor-panel"
        className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-white/80 backdrop-blur-sm"
      >
        <div className="w-full max-w-lg bg-white border border-neutral-200 rounded-2xl shadow-2xl overflow-hidden">
          <div className="px-6 pt-6 pb-4 border-b border-neutral-100">
            <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
              Ask Tutor
            </span>
            <p className="font-serif text-neutral-900 text-xl font-semibold">
              Got it — noted.
            </p>
          </div>
          <div className="mx-6 my-4 px-4 py-3 rounded-xl bg-neutral-50 border border-neutral-200 text-sm text-neutral-600">
            Your question has been recorded. We don&apos;t have a live answer for you yet, but
            we&apos;ll follow up.
          </div>
          <div className="px-6 pb-6 flex justify-end">
            <button
              onClick={play}
              className={`px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                         text-primary text-sm font-semibold transition-all ${FOCUS_RING}`}
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="ask-tutor-panel"
      className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-white/80 backdrop-blur-sm"
    >
      <div className="w-full max-w-lg bg-white border border-neutral-200 rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-neutral-100">
          <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
            Ask Tutor
          </span>
          <p className="font-serif text-neutral-900 text-lg leading-relaxed">
            Didn&apos;t follow that, or have a doubt? Type it below.
          </p>
        </div>

        <div className="px-6 py-4">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What's your question?"
            rows={4}
            autoFocus
            className="w-full bg-neutral-50 border border-neutral-200 rounded-xl px-4 py-3
                       text-neutral-900 text-base sm:text-sm placeholder:text-neutral-400
                       focus:outline-none focus:border-[var(--accent-primary)] focus:ring-4 focus:ring-[var(--accent-primary)]/20
                       resize-none transition-colors"
          />
        </div>

        <div className="px-6 pb-6 flex justify-between items-center">
          <button
            onClick={play}
            className={`text-neutral-500 hover:text-neutral-900 text-sm transition-colors rounded ${FOCUS_RING}`}
          >
            Resume without asking
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting || !text.trim()}
            className={`px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                       text-primary text-sm font-semibold transition-all
                       disabled:opacity-40 disabled:cursor-not-allowed ${FOCUS_RING}`}
          >
            {isSubmitting ? 'Sending…' : 'Submit'}
          </button>
        </div>
      </div>
    </div>
  );
}
