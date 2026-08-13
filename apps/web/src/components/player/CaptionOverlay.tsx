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
      className="absolute bottom-0 inset-x-0 z-10 max-h-[30%] overflow-y-auto overscroll-y-contain
                 bg-black/60 backdrop-blur-sm px-5 py-3 pointer-events-none"
    >
      <p className="text-neutral-100 text-sm leading-relaxed text-center max-w-3xl mx-auto">
        {script}
      </p>
    </div>
  );
}
