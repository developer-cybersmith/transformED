'use client';

import { useState } from 'react';
import { usePlayerStore } from '@/stores/player.machine';
import { submitTeachBack, type TeachBackResult } from '@/lib/assessment';

interface TeachBackModalProps {
  prompt: string;
  segmentTitle: string;
}

export function TeachBackModal({ prompt, segmentTitle }: TeachBackModalProps) {
  const exitTeachBack = usePlayerStore((s) => s.exitTeachBack);
  const sessionId = usePlayerStore((s) => s.sessionId);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const [text, setText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<TeachBackResult | null>(null);

  const segment = lesson?.segments[currentSegmentIndex];

  async function handleSubmit() {
    if (!text.trim() || !lesson || !segment) {
      exitTeachBack();
      return;
    }

    setIsSubmitting(true);
    try {
      const teachBackResult = await submitTeachBack({
        session_id: sessionId,
        lesson_id: lesson.lesson_id,
        segment_id: segment.segment_id,
        response_text: text.trim(),
      });
      setResult(teachBackResult);
    } catch {
      // API unavailable — don't block the student
      exitTeachBack();
    } finally {
      setIsSubmitting(false);
    }
  }

  // Result view — shown after API returns. Never surfaces overall_score or
  // rubric_scores to the student (PRD: no rubric score shown in Phase 1) —
  // only the encouraging, free-text feedback message.
  if (result) {
    return (
      <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-primary-dark/90 backdrop-blur-sm">
        <div className="w-full max-w-lg bg-[#07172C] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
          <div className="px-6 pt-6 pb-4 border-b border-white/5">
            <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
              Teach It Back
            </span>
            <p className="font-serif text-white text-xl font-semibold">
              Nice work!
            </p>
          </div>

          {/* Feedback */}
          {result.feedback && (
            <div className="mx-6 my-4 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-sm text-neutral-300">
              {result.feedback}
            </div>
          )}

          <div className="px-6 pb-6 flex justify-end">
            <button
              onClick={exitTeachBack}
              className="px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                         text-primary text-sm font-semibold transition-all"
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-primary-dark/90 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-[#07172C] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-white/5">
          <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
            Teach It Back
          </span>
          <p className="text-neutral-400 text-xs mb-3">
            {segmentTitle}
          </p>
          <p className="font-serif text-white text-lg leading-relaxed">
            {prompt}
          </p>
        </div>

        {/* Text area */}
        <div className="px-6 py-4">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Type your explanation here…"
            rows={5}
            autoFocus
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3
                       text-white text-sm placeholder:text-neutral-600
                       focus:outline-none focus:border-[var(--accent-primary)]/50
                       resize-none transition-colors"
          />
        </div>

        {/* Actions */}
        <div className="px-6 pb-6 flex justify-between items-center">
          <button
            onClick={exitTeachBack}
            className="text-neutral-500 hover:text-neutral-300 text-sm transition-colors"
          >
            Skip
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting || !text.trim()}
            className="px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                       text-primary text-sm font-semibold transition-all
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isSubmitting ? 'Scoring…' : 'Submit & Continue'}
          </button>
        </div>
      </div>
    </div>
  );
}
