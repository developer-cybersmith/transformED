'use client';

import { useEffect, useRef, useState } from 'react';
import posthog from 'posthog-js';
import { usePlayerStore } from '@/stores/player.machine';
import { submitTeachBack, submitTeachBackAudio, type TeachBackResult } from '@/lib/assessment';
import { FOCUS_RING } from '@/lib/a11y/focusRing';
import { VoiceTeachBackRecorder, isVoiceRecordingSupported } from './VoiceTeachBackRecorder';

interface TeachBackModalProps {
  prompt: string;
  segmentTitle: string;
}

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
export function TeachBackModal({ prompt, segmentTitle }: TeachBackModalProps) {
  const exitTeachBack = usePlayerStore((s) => s.exitTeachBack);
  const sessionId = usePlayerStore((s) => s.sessionId);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const [text, setText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<TeachBackResult | null>(null);
  // Story 2-63 / BR-6. Defaults to 'typed' -- every pre-existing test in this
  // file renders and asserts against the typed view with zero awareness of
  // this toggle, and must keep passing unmodified (AC1).
  const [inputMode, setInputMode] = useState<'typed' | 'voice'>('typed');
  // Evaluated once per mount, not per render -- the browser's own
  // MediaRecorder/getUserMedia support never changes mid-session. Hides the
  // Record tab entirely on an unsupported browser (AC2) rather than showing
  // a button that would only fail when clicked.
  const [voiceSupported] = useState(isVoiceRecordingSupported);
  // Review fix (PR #226): completes the WAI-ARIA Tabs pattern the
  // role="tablist"/role="tab" markup implies -- refs let arrow-key
  // navigation move focus to the newly-active tab, matching native tab
  // behavior (roving tabindex below).
  const typedTabRef = useRef<HTMLButtonElement>(null);
  const voiceTabRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const segment = lesson?.segments[currentSegmentIndex];

  function handleTabKeyDown(e: React.KeyboardEvent<HTMLButtonElement>) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = inputMode === 'typed' ? 'voice' : 'typed';
    setInputMode(next);
    (next === 'typed' ? typedTabRef : voiceTabRef).current?.focus();
  }

  // Review fix (PR #226): was a plain `autoFocus` prop on the textarea. That
  // re-fires every time the student switches back to the Type tab (the
  // textarea unmounts/remounts on each toggle), stealing focus away from
  // whichever tab the arrow-key navigation above just moved it to. A
  // mount-once effect preserves the original "focus the textarea when the
  // modal opens" behavior exactly (still true on first render, since
  // inputMode defaults to 'typed') without re-firing on every toggle.
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  async function handleSubmit() {
    // Bug fix: sessionId can still be '' here -- mintSession (Player.tsx) is
    // async with retries, and a short first segment's teach-back can arrive
    // before it resolves. Postgres rejects '' outright for a uuid column
    // (22P02), a real 500 on every such attempt -- skip the call the same
    // way a missing lesson/segment already does, rather than send a request
    // guaranteed to fail.
    if (!text.trim() || !lesson || !segment || !sessionId) {
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
      // Story 2-54: success path only -- not the empty-text skip above, and
      // not the API-unavailable catch below (that's a failed submission).
      posthog.capture('teachback_submitted', {
        lesson_id: lesson.lesson_id,
        segment_id: segment.segment_id,
      });
    } catch {
      // API unavailable — don't block the student
      exitTeachBack();
    } finally {
      setIsSubmitting(false);
    }
  }

  // Story 2-63 / BR-6: voice submission path, real backend (Story F2-4).
  // Mirrors handleSubmit's own guard/success/failure shape exactly -- same
  // sessionId race (mintSession may not have resolved yet), same
  // never-block-the-student catch, same result view reused unmodified.
  async function handleAudioSubmit(audioBlob: Blob, mimeType: string) {
    if (!lesson || !segment || !sessionId) {
      exitTeachBack();
      return;
    }

    setIsSubmitting(true);
    try {
      const teachBackResult = await submitTeachBackAudio({
        session_id: sessionId,
        segment_id: segment.segment_id,
        audioBlob,
        mimeType,
      });
      setResult(teachBackResult);
      // AC10: deliberately a SEPARATE capture call from handleSubmit's own,
      // not a shared helper with a `source` param -- the typed path's
      // existing exact-match test asserts {lesson_id, segment_id} with no
      // `source` field, and AC1 requires every pre-existing test to pass
      // unmodified.
      posthog.capture('teachback_submitted', {
        lesson_id: lesson.lesson_id,
        segment_id: segment.segment_id,
        source: 'voice',
      });
    } catch {
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
      <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-white/80 backdrop-blur-sm">
        <div className="w-full max-w-lg bg-white border border-neutral-200 rounded-2xl shadow-2xl overflow-hidden">
          <div className="px-6 pt-6 pb-4 border-b border-neutral-100">
            <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
              Teach It Back
            </span>
            <p className="font-serif text-neutral-900 text-xl font-semibold">
              Nice work!
            </p>
          </div>

          {/* Feedback */}
          {result.feedback && (
            <div className="mx-6 my-4 px-4 py-3 rounded-xl bg-neutral-50 border border-neutral-200 text-sm text-neutral-600">
              {result.feedback}
            </div>
          )}

          <div className="px-6 pb-6 flex justify-end">
            <button
              onClick={exitTeachBack}
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
    <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-white/80 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-white border border-neutral-200 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-neutral-100">
          <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
            Teach It Back
          </span>
          <p className="text-neutral-500 text-xs mb-3">
            {segmentTitle}
          </p>
          <p className="font-serif text-neutral-900 text-lg leading-relaxed">
            {prompt}
          </p>
        </div>

        {/* Story 2-63 / BR-6: Type/Record toggle -- only rendered at all when
            the browser actually supports voice recording (AC2). Defaults to
            'typed', so a browser without support renders exactly as before
            this story, with no toggle visible. */}
        {voiceSupported && (
          <div role="tablist" aria-label="Response input mode" className="px-6 pt-3 flex gap-2">
            <button
              ref={typedTabRef}
              type="button"
              id="teachback-tab-typed"
              role="tab"
              aria-selected={inputMode === 'typed'}
              aria-controls="teachback-input-panel"
              tabIndex={inputMode === 'typed' ? 0 : -1}
              onClick={() => setInputMode('typed')}
              onKeyDown={handleTabKeyDown}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${FOCUS_RING} ${
                inputMode === 'typed'
                  ? 'bg-[var(--accent-secondary)] text-primary'
                  : 'bg-neutral-100 text-neutral-500 hover:text-neutral-900'
              }`}
            >
              Type
            </button>
            <button
              ref={voiceTabRef}
              type="button"
              id="teachback-tab-voice"
              role="tab"
              aria-selected={inputMode === 'voice'}
              aria-controls="teachback-input-panel"
              tabIndex={inputMode === 'voice' ? 0 : -1}
              onClick={() => setInputMode('voice')}
              onKeyDown={handleTabKeyDown}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${FOCUS_RING} ${
                inputMode === 'voice'
                  ? 'bg-[var(--accent-secondary)] text-primary'
                  : 'bg-neutral-100 text-neutral-500 hover:text-neutral-900'
              }`}
            >
              Record
            </button>
          </div>
        )}

        <div
          {...(voiceSupported
            ? {
                id: 'teachback-input-panel',
                role: 'tabpanel' as const,
                'aria-labelledby': inputMode === 'typed' ? 'teachback-tab-typed' : 'teachback-tab-voice',
              }
            : {})}
        >
          {inputMode === 'typed' ? (
            <div className="px-6 py-4">
              <textarea
                ref={textareaRef}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Type your explanation here…"
                rows={5}
                className="w-full bg-neutral-50 border border-neutral-200 rounded-xl px-4 py-3
                           text-neutral-900 text-base sm:text-sm placeholder:text-neutral-400
                           focus:outline-none focus:border-[var(--accent-primary)] focus:ring-4 focus:ring-[var(--accent-primary)]/20
                           resize-none transition-colors"
              />
            </div>
          ) : (
            <VoiceTeachBackRecorder onSubmit={handleAudioSubmit} isSubmitting={isSubmitting} />
          )}
        </div>

        {/* Actions. The typed path's own Submit & Continue button only makes
            sense in typed mode -- the voice path submits via
            VoiceTeachBackRecorder's own "Submit Recording" button above,
            since an audio Blob only exists after the recorder finishes
            recording, not from a click on a modal-level button. */}
        <div className="px-6 pb-6 flex justify-between items-center">
          <button
            onClick={exitTeachBack}
            className={`text-neutral-500 hover:text-neutral-900 text-sm transition-colors rounded ${FOCUS_RING}`}
          >
            Skip
          </button>
          {inputMode === 'typed' && (
            <button
              onClick={handleSubmit}
              disabled={isSubmitting || !text.trim()}
              className={`px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                         text-primary text-sm font-semibold transition-all
                         disabled:opacity-40 disabled:cursor-not-allowed ${FOCUS_RING}`}
            >
              {isSubmitting ? 'Scoring…' : 'Submit & Continue'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
