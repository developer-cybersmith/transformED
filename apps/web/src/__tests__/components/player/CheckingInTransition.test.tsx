import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { CheckingInTransition } from '@/components/player/CheckingInTransition';
import { usePlayerStore } from '@/stores/player.machine';

beforeEach(() => {
  usePlayerStore.setState({ tutorState: 'IDLE' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('CheckingInTransition (S2-06 AC5/AC8/AC9)', () => {
  it('renders nothing while tutorState is not CHECKING_IN', () => {
    render(<CheckingInTransition />);
    expect(screen.queryByText(/checking in/i)).toBeNull();
  });

  it('shows the transition on a genuine edge into CHECKING_IN', () => {
    vi.useFakeTimers();
    render(<CheckingInTransition />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });

    expect(screen.queryByText(/checking in/i)).not.toBeNull();
  });

  it('auto-hides after the fixed timer elapses', () => {
    vi.useFakeTimers();
    render(<CheckingInTransition />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });
    expect(screen.queryByText(/checking in/i)).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(screen.queryByText(/checking in/i)).toBeNull();
  });

  it('is not gated on status — it does not read or depend on PlayerStore.status', () => {
    vi.useFakeTimers();
    usePlayerStore.setState({ status: 'QUIZ' });
    render(<CheckingInTransition />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });

    // Still shows even though status is QUIZ — visibility depends only on tutorState (AC9).
    expect(screen.queryByText(/checking in/i)).not.toBeNull();
  });

  it('re-triggers on a second genuine edge into CHECKING_IN after tutorState is reset in between', () => {
    vi.useFakeTimers();
    render(<CheckingInTransition />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(screen.queryByText(/checking in/i)).toBeNull();

    // exitTeachBack() resets tutorState to TEACHING between segments (Task 1.2) —
    // without a genuine value change first, the next CHECKING_IN wouldn't be a new edge.
    act(() => {
      usePlayerStore.setState({ tutorState: 'TEACHING' });
    });
    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });

    expect(screen.queryByText(/checking in/i)).not.toBeNull();
  });

  it('does NOT re-trigger if tutorState is set to CHECKING_IN again without an intervening value change (no-op, same value)', () => {
    vi.useFakeTimers();
    render(<CheckingInTransition />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(screen.queryByText(/checking in/i)).toBeNull();

    // Setting the identical value again is a no-op for a React effect keyed on [tutorState].
    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });

    expect(screen.queryByText(/checking in/i)).toBeNull();
  });
});
