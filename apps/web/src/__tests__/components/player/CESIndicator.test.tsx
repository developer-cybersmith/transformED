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
  ])('score %s -> label "%s" (shown via title tooltip, not visible text — AC-5 40px cap)', (score, label) => {
    act(() => {
      usePlayerStore.setState({ cesScore: score, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    const el = screen.getByTestId('ces-indicator');
    expect(el.getAttribute('title')).toBe(label);
    // AC-5: the label must not also be rendered as permanently-visible text —
    // that's what made the earlier dot+label pill exceed 40px.
    expect(screen.queryByText(label)).toBeNull();
  });

  it('is a fixed 40x40px badge (AC-5) — real size assertion, not just a claim', () => {
    act(() => {
      usePlayerStore.setState({ cesScore: 0.5, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    const el = screen.getByTestId('ces-indicator');
    expect(el.className).toContain('w-10');
    expect(el.className).toContain('h-10');
  });

  it.each([
    ['low', 'bg-red-400'],
    ['engaged', 'bg-amber-400'],
    ['focused', 'bg-emerald-400'],
  ])('band "%s" renders with its corresponding color class (review fix — catches a swapped mapping)', (band, colorClass) => {
    const score = band === 'low' ? 0.1 : band === 'engaged' ? 0.5 : 0.9;
    act(() => {
      usePlayerStore.setState({ cesScore: score, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    const el = screen.getByTestId('ces-indicator');
    expect(el.getAttribute('data-band')).toBe(band);
    expect(el.querySelector('span')?.className).toContain(colorClass);
  });

  it('never renders the raw numeric score anywhere — not in text, not in the title attribute', () => {
    act(() => {
      usePlayerStore.setState({ cesScore: 0.6789, status: 'PLAYING' });
    });
    render(<CESIndicator />);
    const el = screen.getByTestId('ces-indicator');
    expect(el.textContent).not.toMatch(/\d\.\d/);
    expect(el.innerHTML).not.toContain('0.6789');
    expect(el.getAttribute('title')).not.toMatch(/\d\.\d/);
  });
});
