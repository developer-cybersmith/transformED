import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import Player from '@/components/player/Player';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

const { useLessonSocketMock } = vi.hoisted(() => ({
  useLessonSocketMock: vi.fn().mockReturnValue({ status: 'closed', sendAttentionSignal: vi.fn() }),
}));

vi.mock('@/hooks/useLessonSocket', () => ({
  useLessonSocket: useLessonSocketMock,
}));

const originalPlay = window.HTMLMediaElement.prototype.play;
const originalPause = window.HTMLMediaElement.prototype.pause;

beforeEach(() => {
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.pause = vi.fn();
  localStorage.clear();
  useLessonSocketMock.mockClear();
});

afterEach(() => {
  window.HTMLMediaElement.prototype.play = originalPlay;
  window.HTMLMediaElement.prototype.pause = originalPause;
});

// Player's own mount effect calls loadLesson(lesson), which resets status to
// IDLE — so status must be set to ENDED *after* render, not before, or the
// mount effect silently overwrites it.
function renderEnded(sessionId: string) {
  const utils = render(<Player lesson={mockLessonPackage} />);
  act(() => {
    usePlayerStore.setState({ status: 'ENDED', sessionId });
  });
  return utils;
}

describe('Player — lesson complete (ENDED) screen', () => {
  it('links to the session report using the player store sessionId, not a placeholder string', () => {
    renderEnded('sess_abc123');

    const link = screen.getByRole('link', { name: /session report/i });
    expect(link.getAttribute('href')).toBe('/reports/sess_abc123');
    expect(screen.queryByText(/available in Sprint 2/i)).toBeNull();
  });

  it('still shows "Back to Dashboard" alongside the report link', () => {
    renderEnded('sess_abc123');

    const link = screen.getByRole('link', { name: /back to dashboard/i });
    expect(link.getAttribute('href')).toBe('/dashboard');
  });

  it('does not render a report link to /reports/undefined when sessionId is empty', () => {
    renderEnded('');

    expect(screen.queryByRole('link', { name: /session report/i })).toBeNull();
    expect(screen.getByRole('link', { name: /back to dashboard/i })).not.toBeNull();
  });
});

describe('Player — restores saved progress on mount (S2-05)', () => {
  it('restores segment index, slide, and quizFiredForSegment from a valid saved snapshot', () => {
    localStorage.setItem(
      `hie:session:${mockLessonPackage.lesson_id}`,
      JSON.stringify({
        segmentIndex: 1,
        audioPositionMs: 80000, // within seg_1's sl_1_1 window (74000-148000)
        quizFiredForSegment: ['seg_0'],
        storedAt: Date.now(),
      })
    );

    render(<Player lesson={mockLessonPackage} />);

    const state = usePlayerStore.getState();
    expect(state.currentSegmentIndex).toBe(1);
    expect(state.currentSlideId).toBe('sl_1_1');
    expect(state.quizFiredForSegment.has('seg_0')).toBe(true);
  });

  it('starts fresh at segment 0 when no saved snapshot exists', () => {
    render(<Player lesson={mockLessonPackage} />);

    expect(usePlayerStore.getState().currentSegmentIndex).toBe(0);
  });
});

describe('Player — lesson WebSocket (S2-06)', () => {
  it('mounts useLessonSocket with the store sessionId, so the socket actually connects during a real session', () => {
    render(<Player lesson={mockLessonPackage} />);

    expect(useLessonSocketMock).toHaveBeenCalledWith(usePlayerStore.getState().sessionId);
  });

  it('mounts CheckingInTransition — it becomes visible when tutorState is CHECKING_IN', () => {
    render(<Player lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });

    expect(screen.queryByText(/checking in/i)).not.toBeNull();
  });
});
