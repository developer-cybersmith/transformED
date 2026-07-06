import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import Player from '@/components/player/Player';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

const originalPlay = window.HTMLMediaElement.prototype.play;
const originalPause = window.HTMLMediaElement.prototype.pause;

beforeEach(() => {
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.pause = vi.fn();
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
});
