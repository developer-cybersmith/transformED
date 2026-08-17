import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CaptionOverlay } from '@/components/player/CaptionOverlay';

// ── Tests ────────────────────────────────────────────────────────────────────

describe('CaptionOverlay — content', () => {
  it('renders the narration script text when present', () => {
    render(<CaptionOverlay script="Welcome to the tutorial. Today we cover SQL injection." />);
    expect(
      screen.getByText(/Welcome to the tutorial\. Today we cover SQL injection\./)
    ).toBeDefined();
  });

  it('renders the caption panel container when a script is present', () => {
    render(<CaptionOverlay script="Some narration text." />);
    expect(screen.getByTestId('caption-overlay')).toBeDefined();
  });

  it('review fix: the caption panel must accept pointer events so its own overflow-y-auto scroll actually works', () => {
    // Regression for a real, browser-verified bug: `pointer-events-none`
    // alongside `overflow-y-auto` blocks ALL wheel/mouse-driven scrolling on
    // the element (no keyboard path either -- this is a plain non-focusable
    // div), silently clipping any narration longer than ~30% of the slide
    // area's height with no way to read the rest. jsdom can't compute real
    // scrollHeight/clientHeight or CSS cascade effects, so this asserts the
    // class directly -- the only thing that actually caused the bug.
    render(<CaptionOverlay script="Some narration text." />);
    const overlay = screen.getByTestId('caption-overlay');
    expect(overlay.className).not.toMatch(/pointer-events-none/);
  });
});

describe('CaptionOverlay — render nothing when there is nothing to show', () => {
  it('renders nothing when script is null', () => {
    const { container } = render(<CaptionOverlay script={null} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('caption-overlay')).toBeNull();
  });

  it('renders nothing when script is an empty string', () => {
    const { container } = render(<CaptionOverlay script="" />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('caption-overlay')).toBeNull();
  });
});
