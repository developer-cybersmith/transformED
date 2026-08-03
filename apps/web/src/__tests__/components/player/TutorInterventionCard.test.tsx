import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { TutorInterventionCard } from '@/components/player/TutorInterventionCard';
import { usePlayerStore } from '@/stores/player.machine';

beforeEach(() => {
  usePlayerStore.setState({ activeIntervention: null, status: 'PLAYING' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TutorInterventionCard (S3-03 AC-3/AC-4/AC-5)', () => {
  it('renders nothing when there is no active intervention', () => {
    render(<TutorInterventionCard />);
    expect(screen.queryByTestId('tutor-intervention-card')).toBeNull();
  });

  it('renders the message when an intervention is active', () => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'Stay with me!' },
      });
    });
    render(<TutorInterventionCard />);
    expect(screen.getByTestId('tutor-intervention-card')).not.toBeNull();
    expect(screen.getByText('Stay with me!')).not.toBeNull();
  });

  it.each([
    ['distraction'],
    ['confusion'],
    ['fatigue'],
  ])('renders the %s variant with a matching data-variant attribute', (type) => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: type as 'distraction' | 'confusion' | 'fatigue', message: 'x' },
      });
    });
    render(<TutorInterventionCard />);
    expect(screen.getByTestId('tutor-intervention-card').getAttribute('data-variant')).toBe(type);
  });

  it('never renders while status is TEACH_BACK, even with an active intervention (render-level guard)', () => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'confusion', message: 'x' },
        status: 'TEACH_BACK',
      });
    });
    render(<TutorInterventionCard />);
    expect(screen.queryByTestId('tutor-intervention-card')).toBeNull();
  });

  it('hides immediately if status transitions to TEACH_BACK while a card is already showing', () => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'confusion', message: 'x' },
        status: 'PLAYING',
      });
    });
    render(<TutorInterventionCard />);
    expect(screen.getByTestId('tutor-intervention-card')).not.toBeNull();

    act(() => {
      usePlayerStore.setState({ status: 'TEACH_BACK' });
    });
    expect(screen.queryByTestId('tutor-intervention-card')).toBeNull();
  });
});

describe('TutorInterventionCard dismissal (S3-03 AC-6)', () => {
  it('dismisses on button click', () => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
      });
    });
    render(<TutorInterventionCard />);
    expect(screen.getByTestId('tutor-intervention-card')).not.toBeNull();

    act(() => {
      screen.getByRole('button', { name: /dismiss/i }).click();
    });

    expect(usePlayerStore.getState().activeIntervention).toBeNull();
  });

  it('auto-dismisses after exactly 30000ms', () => {
    vi.useFakeTimers();
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
      });
    });
    render(<TutorInterventionCard />);

    act(() => {
      vi.advanceTimersByTime(29_999);
    });
    expect(usePlayerStore.getState().activeIntervention).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(usePlayerStore.getState().activeIntervention).toBeNull();
  });

  it('does not fire a stale timer against a replacement intervention', () => {
    vi.useFakeTimers();
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'first' },
      });
    });
    const { rerender } = render(<TutorInterventionCard />);

    // 20s in, a new intervention replaces the first — its own timer should
    // now govern; the first timer must not fire and clear this newer one.
    act(() => {
      vi.advanceTimersByTime(20_000);
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'confusion', message: 'second' },
      });
    });
    rerender(<TutorInterventionCard />);

    // 10s more — 30s past the FIRST intervention's start, but only 10s past the second's.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(usePlayerStore.getState().activeIntervention).toEqual({
      session_id: 's1',
      type: 'confusion',
      message: 'second',
    });

    // 20s more — 30s past the second intervention's start.
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(usePlayerStore.getState().activeIntervention).toBeNull();
  });

  it('clears the timer on unmount (no act-of-god update after unmount)', () => {
    vi.useFakeTimers();
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
      });
    });
    const { unmount } = render(<TutorInterventionCard />);
    unmount();

    expect(() => {
      act(() => {
        vi.advanceTimersByTime(30_000);
      });
    }).not.toThrow();
  });
});
