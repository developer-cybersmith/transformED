import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { CESIndicator } from '@/components/player/CESIndicator';
import { usePlayerStore } from '@/stores/player.machine';

beforeEach(() => {
  usePlayerStore.setState({ cesScore: null, status: 'PLAYING' });
});

describe('CESIndicator (S3-04 AC-3/AC-4/AC-5)', () => {
  it('renders nothing when cesScore is null', () => {
    render(<CESIndicator />);
    expect(screen.queryByTestId('ces-indicator')).toBeNull();
  });

  it('renders nothing when status is not PLAYING, even with a score', () => {
    act(() => {
      usePlayerStore.setState({ cesScore: 0.5, status: 'QUIZ' });
    });
    render(<CESIndicator />);
    expect(screen.queryByTestId('ces-indicator')).toBeNull();
  });

  it('hides immediately when status changes away from PLAYING while a score is active', () => {
    act(() => {
      usePlayerStore.setState({ cesScore: 0.5, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    expect(screen.getByTestId('ces-indicator')).not.toBeNull();

    act(() => {
      usePlayerStore.setState({ status: 'QUIZ' });
    });
    expect(screen.queryByTestId('ces-indicator')).toBeNull();
  });

  it.each([
    [0.1, 'Low'],
    [0.39, 'Low'],
    [0.4, 'Engaged'],
    [0.55, 'Engaged'],
    [0.7, 'Engaged'],
    [0.71, 'Focused'],
    [1.0, 'Focused'],
  ])('shows "%s" -> label "%s"', (score, label) => {
    act(() => {
      usePlayerStore.setState({ cesScore: score, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    expect(screen.getByText(label)).not.toBeNull();
  });

  it('never renders the raw numeric score anywhere in its output', () => {
    act(() => {
      usePlayerStore.setState({ cesScore: 0.6789, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    const el = screen.getByTestId('ces-indicator');
    expect(el.textContent).not.toMatch(/\d\.\d/);
    expect(el.innerHTML).not.toContain('0.6789');
  });
});
