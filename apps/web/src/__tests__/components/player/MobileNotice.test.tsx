import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MobileNotice } from '@/components/player/MobileNotice';

// jsdom has no matchMedia -- same mocking pattern as AttentionChart.test.tsx,
// the one existing precedent for testing useMediaQuery-driven components.
function mockMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

describe('MobileNotice', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the desktop-recommended banner when the viewport is mobile-width', () => {
    mockMatchMedia(true);
    render(<MobileNotice />);

    expect(screen.getByTestId('mobile-notice')).not.toBeNull();
    expect(screen.getByText(/designed for desktop/i)).not.toBeNull();
  });

  it('renders nothing when the viewport is desktop-width', () => {
    mockMatchMedia(false);
    render(<MobileNotice />);

    expect(screen.queryByTestId('mobile-notice')).toBeNull();
  });

  it('dismisses on click and does not reappear on re-render (same mount)', () => {
    mockMatchMedia(true);
    const { rerender } = render(<MobileNotice />);

    expect(screen.getByTestId('mobile-notice')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(screen.queryByTestId('mobile-notice')).toBeNull();

    rerender(<MobileNotice />);
    expect(screen.queryByTestId('mobile-notice')).toBeNull();
  });

  it('is a small informational banner, never a full-screen blocking overlay (AC-2: never gates the player)', () => {
    mockMatchMedia(true);
    render(<MobileNotice />);

    const notice = screen.getByTestId('mobile-notice');
    // A blocking overlay in this codebase is always `inset-0` (see audioError/
    // ENDED overlays in Player.tsx) -- the banner must never use that pattern.
    expect(notice.className).not.toMatch(/inset-0/);
  });
});
