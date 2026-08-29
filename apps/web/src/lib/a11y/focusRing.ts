// Shared focus-visible treatment, matching components/ui/button.tsx's
// existing ring so raw <button> elements (which don't use the shared Button
// component) still get a visually consistent focus indicator.
export const FOCUS_RING =
  'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20';
