'use client';

interface CaptionOverlayProps {
  /** Current segment's full narration script. Pass `segment?.narration.script ?? null`. */
  script: string | null;
}

// Story 3-53 / D90. Deliberately NOT synced to word/sentence-level timestamps --
// the Sarvam TTS integration currently returns empty word-level timestamps
// (a separate, larger follow-up), so this shows the current segment's whole
// script at once, non-synced, updating only when the segment itself changes.
// No show/hide toggle in this first pass -- a reasonable near-term
// enhancement, explicitly out of scope here.
export function CaptionOverlay({ script }: CaptionOverlayProps) {
  // Render nothing when there is nothing to show -- mirrors SlideImage's own
  // "render nothing rather than a blank space-eating placeholder" pattern in
  // SlideRenderer.tsx.
  if (!script) return null;

  return (
    <div
      data-testid="caption-overlay"
      // Review fix (2026-08-17), two bugs stacked on the same root cause --
      // this element's own overflow-y-auto scroll was completely unreachable:
      // (1) this div used to also carry `pointer-events-none`, which blocks
      //     ALL mouse/wheel interaction with the element outright.
      // (2) even with pointer-events restored, SmoothScroll.tsx's global
      //     Lenis instance hijacks wheel events for the whole document by
      //     default -- SlideRenderer.tsx (the sibling component sharing this
      //     same slide-area container) already carries `data-lenis-prevent`
      //     for exactly this reason; CaptionOverlay never got it.
      // Verified live against a real deployed lesson: a real narration
      // segment clipped 390 of 616px (~63%) of its own text with NO way to
      // read the rest -- no scroll, no keyboard path (plain non-focusable
      // div). Silently dropping most of "so students can read along" content
      // is the exact class of bug this app treats as unacceptable at the
      // content-pipeline level; it applies here too.
      data-lenis-prevent
      className="absolute bottom-0 inset-x-0 z-10 max-h-[30%] overflow-y-auto overscroll-y-contain
                 bg-black/60 backdrop-blur-sm px-5 py-3"
    >
      <p className="text-neutral-100 text-sm leading-relaxed text-center max-w-3xl mx-auto">
        {script}
      </p>
    </div>
  );
}
