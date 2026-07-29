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

// Default no-op refetch for tests that don't care about the retry-refetch
// flow (S2-33) -- resolves to null, i.e. "refetch didn't return fresh content".
const mockOnRefetchLesson = vi.fn().mockResolvedValue(null);

beforeEach(() => {
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.pause = vi.fn();
  localStorage.clear();
  useLessonSocketMock.mockClear();
  mockOnRefetchLesson.mockClear();
  mockOnRefetchLesson.mockResolvedValue(null);
});

afterEach(() => {
  window.HTMLMediaElement.prototype.play = originalPlay;
  window.HTMLMediaElement.prototype.pause = originalPause;
});

// Player's own mount effect calls loadLesson(lesson), which resets status to
// IDLE — so status must be set to ENDED *after* render, not before, or the
// mount effect silently overwrites it.
function renderEnded(sessionId: string) {
  const utils = render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);
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

describe('Player — tier badge (S2-10)', () => {
  it('shows the mapped tier label for the lesson\'s tier (T2 -> Standard)', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    expect(screen.getByText('Standard')).not.toBeNull();
  });

  it('shows a different label for a different tier (T1 -> Full-Depth)', () => {
    const t1Lesson = { ...mockLessonPackage, metadata: { ...mockLessonPackage.metadata, tier: 'T1' as const } };

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={t1Lesson} />);

    expect(screen.getByText('Full-Depth')).not.toBeNull();
    expect(screen.queryByText('Standard')).toBeNull();
  });

  it('shows the T3 label (Refresher)', () => {
    const t3Lesson = { ...mockLessonPackage, metadata: { ...mockLessonPackage.metadata, tier: 'T3' as const } };

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={t3Lesson} />);

    expect(screen.getByText('Refresher')).not.toBeNull();
  });

  it('falls back gracefully instead of rendering "undefined" for an unrecognized/missing tier (review fix)', () => {
    const badLesson = {
      ...mockLessonPackage,
      metadata: { ...mockLessonPackage.metadata, tier: 'T99' as unknown as 'T1' },
    };

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={badLesson} />);

    expect(screen.queryByText('undefined')).toBeNull();
    expect(screen.getByText('Standard')).not.toBeNull();
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

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    const state = usePlayerStore.getState();
    expect(state.currentSegmentIndex).toBe(1);
    expect(state.currentSlideId).toBe('sl_1_1');
    expect(state.quizFiredForSegment.has('seg_0')).toBe(true);
  });

  it('starts fresh at segment 0 when no saved snapshot exists', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    expect(usePlayerStore.getState().currentSegmentIndex).toBe(0);
  });
});

describe('Player — audio buffering / error retry UI (S2-26)', () => {
  it('shows the buffering indicator when isBuffering is true and status is PLAYING', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ status: 'PLAYING', isBuffering: true });
    });

    expect(screen.getByTestId('audio-buffering')).not.toBeNull();
  });

  it('does not show the buffering indicator when isBuffering is false', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    expect(screen.queryByTestId('audio-buffering')).toBeNull();
  });

  it('does not show the buffering indicator while not PLAYING (e.g. PAUSED), even if isBuffering is true', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ status: 'PAUSED', isBuffering: true });
    });

    expect(screen.queryByTestId('audio-buffering')).toBeNull();
  });

  it('shows the playback-error state with a Retry button when audioError is true', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    expect(screen.getByTestId('audio-error')).not.toBeNull();
    expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull();
  });

  it('clicking Retry calls retryAudio(), clearing audioError', async () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    await act(async () => {
      screen.getByRole('button', { name: /retry/i }).click();
    });

    expect(usePlayerStore.getState().audioError).toBe(false);
    expect(screen.queryByTestId('audio-error')).toBeNull();
  });

  it('clicking Retry calls onRefetchLesson (S2-33) before retrying, so an expired signed URL has a chance to be refreshed', async () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    await act(async () => {
      screen.getByRole('button', { name: /retry/i }).click();
    });

    expect(mockOnRefetchLesson).toHaveBeenCalledTimes(1);
  });

  it('applies fresh lesson content from a successful refetch via refreshLessonMedia before retrying (S2-33)', async () => {
    const refreshedLesson = { ...mockLessonPackage, metadata: { ...mockLessonPackage.metadata, title: 'Refreshed Title' } };
    mockOnRefetchLesson.mockResolvedValueOnce({
      status: 'ready' as const,
      error: null,
      content: refreshedLesson,
    });

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    await act(async () => {
      screen.getByRole('button', { name: /retry/i }).click();
    });

    expect(usePlayerStore.getState().lesson).toBe(refreshedLesson);
    expect(usePlayerStore.getState().audioError).toBe(false);
  });

  it('disables the Retry button and ignores a second click while a refetch is still in flight (review fix -- prevents a rapid double-click from double-applying the retry)', async () => {
    let resolveRefetch!: (value: null) => void;
    mockOnRefetchLesson.mockImplementationOnce(
      () => new Promise((resolve) => { resolveRefetch = resolve; })
    );

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    act(() => {
      screen.getByRole('button', { name: /retry/i }).click();
    });

    const button = screen.getByRole('button', { name: /retrying/i });
    expect(button.hasAttribute('disabled')).toBe(true);

    // Second click while in flight must not fire another refetch.
    act(() => {
      button.click();
    });
    expect(mockOnRefetchLesson).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRefetch(null);
      await Promise.resolve();
    });

    expect(usePlayerStore.getState().audioError).toBe(false);
  });

  it('still calls retryAudio() even when onRefetchLesson rejects, so Retry never becomes permanently non-functional (S2-33)', async () => {
    mockOnRefetchLesson.mockRejectedValueOnce(new Error('network error'));

    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    await act(async () => {
      screen.getByRole('button', { name: /retry/i }).click();
    });

    expect(usePlayerStore.getState().audioError).toBe(false);
  });

  it('does NOT reset playback progress when re-rendered with a NEW lesson object for the SAME lesson_id (review fix -- this is exactly what a real retry-refetch produces via SWR mutate(), and previously silently reset the whole player via the loadLesson-on-prop-change mount effect)', () => {
    const { rerender } = render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({
        status: 'PLAYING',
        currentSegmentIndex: 1,
        audioPositionMs: 5000,
        quizFiredForSegment: new Set(['seg_0']),
      });
    });
    const sessionIdBefore = usePlayerStore.getState().sessionId;

    // A deep-cloned lesson object, same lesson_id -- exactly what a fresh SWR
    // fetch of the same lesson produces (new object identity, same content).
    const refetchedLesson = JSON.parse(JSON.stringify(mockLessonPackage));
    rerender(<Player onRefetchLesson={mockOnRefetchLesson} lesson={refetchedLesson} />);

    const state = usePlayerStore.getState();
    expect(state.status).toBe('PLAYING');
    expect(state.currentSegmentIndex).toBe(1);
    expect(state.audioPositionMs).toBe(5000);
    expect(state.quizFiredForSegment.has('seg_0')).toBe(true);
    expect(state.sessionId).toBe(sessionIdBefore);
  });

  it('does NOT show the playback-error overlay during QUIZ, even if audioError is true (review fix — a stale error must not block the quiz)', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ status: 'QUIZ', audioError: true });
    });

    expect(screen.queryByTestId('audio-error')).toBeNull();
  });

  it('does NOT show the playback-error overlay during TEACH_BACK, even if audioError is true (review fix)', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ status: 'TEACH_BACK', audioError: true });
    });

    expect(screen.queryByTestId('audio-error')).toBeNull();
  });

  it('does NOT show the playback-error overlay when ENDED, even if audioError is true (review fix)', () => {
    renderEnded('sess_abc123');

    act(() => {
      usePlayerStore.setState({ audioError: true });
    });

    expect(screen.queryByTestId('audio-error')).toBeNull();
  });

  it('shows extra guidance text after 3+ retries on the same segment (review fix — no cap/backoff existed before)', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true, audioRetryCount: 3 });
    });

    expect(screen.getByText(/still not working after several tries/i)).not.toBeNull();
  });

  it('does not show the repeated-failure guidance text before the threshold', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ audioError: true, audioRetryCount: 1 });
    });

    expect(screen.queryByText(/still not working after several tries/i)).toBeNull();
  });
});

describe('Player — lesson WebSocket (S2-06)', () => {
  it('mounts useLessonSocket with the store sessionId, so the socket actually connects during a real session', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    expect(useLessonSocketMock).toHaveBeenCalledWith(usePlayerStore.getState().sessionId);
  });

  it('mounts CheckingInTransition — it becomes visible when tutorState is CHECKING_IN', () => {
    render(<Player onRefetchLesson={mockOnRefetchLesson} lesson={mockLessonPackage} />);

    act(() => {
      usePlayerStore.setState({ tutorState: 'CHECKING_IN' });
    });

    expect(screen.queryByText(/checking in/i)).not.toBeNull();
  });
});
