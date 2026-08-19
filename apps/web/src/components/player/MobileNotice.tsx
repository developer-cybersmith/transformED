'use client';

import { useState } from 'react';
import { useMediaQuery } from '@/hooks/use-media-query';

/**
 * Informational-only "desktop recommended" banner (Story 2-49 / S3-08, AC-1/AC-2).
 * The lesson player is desktop-first per the PRD -- this surfaces that honestly
 * instead of leaving mobile students with a silently broken layout, but it
 * never blocks or gates the player: no `inset-0` backdrop, no disabling of
 * controls underneath. Dismissible for the current mount only -- no
 * persistence across reloads, since re-showing on a fresh visit is the
 * correct behavior for a real constraint, not an annoyance to suppress.
 *
 * Reuses the existing `useMediaQuery` hook exactly as `AttentionChart.tsx`
 * already does -- no new breakpoint hook or library (AC-7). `767px` matches
 * Tailwind's `md` cutoff, consistent with every other viewport check in this
 * codebase.
 */
export function MobileNotice() {
  const isMobile = useMediaQuery('(max-width: 767px)');
  const [dismissed, setDismissed] = useState(false);

  if (!isMobile || dismissed) return null;

  return (
    <div
      data-testid="mobile-notice"
      role="status"
      className="absolute top-0 inset-x-0 z-30 flex items-center justify-between gap-3 px-4 py-2 bg-neutral-900/95 text-white text-xs"
    >
      <span>This lesson is designed for desktop. For the best experience, switch to a larger screen.</span>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => setDismissed(true)}
        className="shrink-0 text-white/70 hover:text-white transition-colors"
      >
        ✕
      </button>
    </div>
  );
}
