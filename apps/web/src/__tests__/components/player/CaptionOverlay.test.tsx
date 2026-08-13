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
