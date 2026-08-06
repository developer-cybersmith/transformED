'use client';

import { useState } from 'react';
import { useAttentionConsent } from '@/hooks/useAttentionConsent';

/**
 * S3-01. Shown once (per `useAttentionConsent`'s dismissal tracking) before
 * any camera code exists to gate — S3-02 (AttentionMonitor) is a separate,
 * not-yet-started story. This component makes no camera/MediaPipe call of
 * any kind; it only explains the feature and records the student's choice.
 *
 * `accept()` writes directly to `public.user_consents` via Supabase (RLS
 * allows an own-row insert; a trigger syncs `users.attention_consent`), so
 * this works today without any backend endpoint. The failure path below
 * still matters for real failures (RLS denial, network error) and must
 * never trap the student.
 */
export function AttentionConsentModal() {
  const { showModal, accept, decline } = useAttentionConsent();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [acceptFailed, setAcceptFailed] = useState(false);

  if (!showModal) return null;

  async function handleAccept() {
    setIsSubmitting(true);
    setAcceptFailed(false);
    try {
      await accept();
    } catch (err) {
      // A genuine, unexpected failure (e.g. RLS denial, network error) --
      // accept() has already logged the underlying cause. The student is
      // never blocked behind this modal either way.
      console.error('AttentionConsentModal: accept failed', err);
      setAcceptFailed(true);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div
      data-testid="attention-consent-modal"
      className="absolute inset-0 z-30 flex items-center justify-center p-6 bg-primary-dark/90 backdrop-blur-sm"
    >
      <div className="w-full max-w-lg bg-[#07172C] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-white/5">
          <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider block mb-1">
            Attention Monitoring
          </span>
          <h2 className="font-serif text-white text-xl font-semibold">Help your tutor notice when you drift</h2>
        </div>

        <div className="px-6 py-5 flex flex-col gap-3 text-neutral-300 text-sm leading-relaxed">
          <p>
            With your permission, this lesson can use your device&apos;s webcam to notice when your
            attention drifts, so the tutor can gently check in.
          </p>
          <p>
            Only five aggregate numbers are ever sent — head position, blink rate, and similar
            summaries. <strong className="text-white font-medium">Raw video never leaves your browser</strong>,
            never is it recorded, and never is it stored.
          </p>
          <p>You can decline. Declining does not change your lesson in any way.</p>

          {acceptFailed && (
            <div
              role="alert"
              className="mt-1 flex flex-col gap-2 rounded-xl border border-red-400/30 bg-red-950/40 px-4 py-3 text-red-200"
            >
              <span>We couldn&apos;t save your choice just now. You can try again, or continue without this.</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleAccept}
                  disabled={isSubmitting}
                  className="px-3 py-1.5 rounded-full border border-red-300/40 text-xs font-medium hover:bg-red-900/40 disabled:opacity-60"
                >
                  Retry
                </button>
                <button
                  type="button"
                  onClick={decline}
                  className="px-3 py-1.5 rounded-full border border-red-300/40 text-xs font-medium hover:bg-red-900/40"
                >
                  Continue without this
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="px-6 pb-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={decline}
            className="px-4 py-2 rounded-full text-neutral-400 text-sm font-medium hover:text-white transition-colors"
          >
            Decline
          </button>
          <button
            type="button"
            onClick={handleAccept}
            disabled={isSubmitting}
            className="px-5 py-2 rounded-full bg-[var(--accent-secondary)] text-primary text-sm font-semibold hover:brightness-105 transition-all disabled:opacity-60"
          >
            {isSubmitting ? 'Saving…' : 'Accept'}
          </button>
        </div>
      </div>
    </div>
  );
}
