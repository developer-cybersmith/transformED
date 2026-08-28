import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { TutorInterventionCard } from '@/components/player/TutorInterventionCard';
import { usePlayerStore } from '@/stores/player.machine';

const { captureMock } = vi.hoisted(() => ({
  captureMock: vi.fn(),
}));

vi.mock('posthog-js', () => ({
  default: { capture: captureMock },
}));

beforeEach(() => {
  usePlayerStore.setState({
    activeIntervention: null,
    status: 'PLAYING',
    wsSendControl: null,
    sessionId: '',
    lesson: null,
  });
  captureMock.mockReset();
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

  it('Story 2-54: fires intervention_received once (with lesson/session context), even after a TEACH_BACK visibility round-trip for the same payload', () => {
    usePlayerStore.setState({ sessionId: 'sess_1', lesson: { lesson_id: 'lesson_1' } as never });
    const payload = { session_id: 's1', type: 'confusion' as const, message: 'x' };
    act(() => {
      usePlayerStore.setState({ activeIntervention: payload, status: 'PLAYING' });
    });
    render(<TutorInterventionCard />);
    expect(captureMock).toHaveBeenCalledWith('intervention_received', {
      intervention_type: 'confusion',
      lesson_id: 'lesson_1',
      session_id: 'sess_1',
    });
    expect(captureMock).toHaveBeenCalledTimes(1);

    // activeIntervention is NOT cleared by a TEACH_BACK transition (only
    // hidden) -- ending back to PLAYING re-shows the SAME payload (same
    // object reference, unchanged).
    act(() => {
      usePlayerStore.setState({ status: 'TEACH_BACK' });
    });
    act(() => {
      usePlayerStore.setState({ status: 'PLAYING' });
    });

    expect(screen.getByTestId('tutor-intervention-card')).not.toBeNull();
    expect(captureMock).toHaveBeenCalledTimes(1);
  });

  // Review fix (Edge Case Hunter): interventions are pre-generated from a
  // small fixed set of messages per lesson (CLAUDE.md), so two GENUINELY
  // DIFFERENT dispatches can easily share identical type+message content.
  // A content-hash guard would wrongly suppress the second, real
  // intervention_received -- the fix keys on object-reference identity
  // instead, which correctly distinguishes "same object shown again" from
  // "a new object with the same content."
  it('Story 2-54: fires intervention_received again for a genuinely NEW intervention with identical content to a previous one', () => {
    const first = { session_id: 's1', type: 'distraction' as const, message: 'Stay with me!' };
    act(() => {
      usePlayerStore.setState({ activeIntervention: first, status: 'PLAYING' });
    });
    render(<TutorInterventionCard />);
    expect(captureMock).toHaveBeenCalledTimes(1);

    // A fresh dispatch with IDENTICAL content but a NEW object reference --
    // e.g. the tutor firing the same pre-generated distraction message a
    // second time later in the session.
    const second = { session_id: 's1', type: 'distraction' as const, message: 'Stay with me!' };
    act(() => {
      usePlayerStore.setState({ activeIntervention: null });
    });
    act(() => {
      usePlayerStore.setState({ activeIntervention: second });
    });

    expect(captureMock).toHaveBeenCalledTimes(2);
    expect(captureMock).toHaveBeenNthCalledWith(
      2,
      'intervention_received',
      expect.objectContaining({ intervention_type: 'distraction' })
    );
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

  // Bug fix (found live, 2026-08-12): dismissal only ever cleared local React
  // state -- the server-side FSM never learned the intervention ended, so it
  // stayed stuck in INTERVENING forever and CES monitoring silently died for
  // the rest of every session after its first intervention.
  it('sends intervention_complete over the WebSocket on manual dismiss', () => {
    const wsSendControl = vi.fn();
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
        wsSendControl,
      });
    });
    render(<TutorInterventionCard />);

    act(() => {
      screen.getByRole('button', { name: /dismiss/i }).click();
    });

    expect(wsSendControl).toHaveBeenCalledWith({ type: 'intervention_complete' });
  });

  it('sends intervention_complete over the WebSocket on auto-dismiss', () => {
    vi.useFakeTimers();
    const wsSendControl = vi.fn();
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
        wsSendControl,
      });
    });
    render(<TutorInterventionCard />);

    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(wsSendControl).toHaveBeenCalledWith({ type: 'intervention_complete' });
  });

  it('does not throw when wsSendControl is null (socket never connected)', () => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
        wsSendControl: null,
      });
    });
    render(<TutorInterventionCard />);

    expect(() => {
      act(() => {
        screen.getByRole('button', { name: /dismiss/i }).click();
      });
    }).not.toThrow();
  });

  it('auto-dismisses after exactly 30000ms, removing the card from the DOM (not just the store)', () => {
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
    expect(screen.queryByTestId('tutor-intervention-card')).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(usePlayerStore.getState().activeIntervention).toBeNull();
    expect(screen.queryByTestId('tutor-intervention-card')).toBeNull();
  });

  it('does not start the 30s window until the card becomes visible (AC-6, review fix)', () => {
    vi.useFakeTimers();
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'x' },
        status: 'TEACH_BACK', // hidden by the render-level guard
      });
    });
    render(<TutorInterventionCard />);

    // Well past 30s while hidden -- the clock must not have been running.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(usePlayerStore.getState().activeIntervention).not.toBeNull();

    // Becomes visible now -- a fresh 30s window starts from this moment.
    act(() => {
      usePlayerStore.setState({ status: 'PLAYING' });
    });
    expect(screen.queryByTestId('tutor-intervention-card')).not.toBeNull();

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

describe('TutorInterventionCard robustness (review fixes)', () => {
  it('falls back to a default style (and does not throw) for an unrecognized type value', () => {
    act(() => {
      usePlayerStore.setState({
        // A malformed/unexpected type that TS would normally reject -- simulates
        // a runtime value from a server bug or contract drift.
        activeIntervention: { session_id: 's1', type: 'unknown' as never, message: 'x' },
      });
    });
    expect(() => render(<TutorInterventionCard />)).not.toThrow();
    const card = screen.getByTestId('tutor-intervention-card');
    expect(card.getAttribute('data-variant')).toBe('unknown');
    expect(screen.getByText('x')).not.toBeNull();
  });

  it('remounts (fresh render identity) when a replacement intervention has identical message text but a different type', () => {
    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'distraction', message: 'Same text' },
      });
    });
    render(<TutorInterventionCard />);
    expect(screen.getByTestId('tutor-intervention-card').getAttribute('data-variant')).toBe('distraction');

    act(() => {
      usePlayerStore.setState({
        activeIntervention: { session_id: 's1', type: 'fatigue', message: 'Same text' },
      });
    });

    expect(screen.getByTestId('tutor-intervention-card').getAttribute('data-variant')).toBe('fatigue');
  });
});
