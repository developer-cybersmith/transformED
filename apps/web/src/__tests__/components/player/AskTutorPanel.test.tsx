import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AskTutorPanel } from '@/components/player/AskTutorPanel';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

const { submitTutorQuestionMock } = vi.hoisted(() => ({
  submitTutorQuestionMock: vi.fn(),
}));

vi.mock('@/lib/assessment', () => ({
  submitTutorQuestion: submitTutorQuestionMock,
}));

beforeEach(() => {
  submitTutorQuestionMock.mockReset();
  submitTutorQuestionMock.mockResolvedValue({ received: true });
  usePlayerStore.getState().loadLesson(mockLessonPackage);
  // Ask Tutor is reachable from PLAYING or an existing PAUSED state (any
  // reason) -- 'intervention' is the realistic value by the time this panel
  // actually mounts (Player.tsx gates on it), matching real usage.
  usePlayerStore.setState({
    status: 'PAUSED',
    pauseReason: 'intervention',
    currentSegmentIndex: 0,
    sessionId: 'sess_42',
    audioPositionMs: 12345,
  });
});

describe('AskTutorPanel — Story 2-57 / BR-5, D159 (capture-and-log only)', () => {
  it('disables submit until text is entered', async () => {
    render(<AskTutorPanel />);
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.type(screen.getByPlaceholderText("What's your question?"), 'Why does this work?');
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('submits with the documented D159 payload shape (segment_id, question_text, audio_position_ms)', async () => {
    render(<AskTutorPanel />);
    await userEvent.type(screen.getByPlaceholderText("What's your question?"), 'Why does this work?');
    await userEvent.click(screen.getByRole('button', { name: /submit/i }));

    expect(submitTutorQuestionMock).toHaveBeenCalledWith({
      session_id: 'sess_42',
      segment_id: mockLessonPackage.segments[0].segment_id,
      question_text: 'Why does this work?',
      audio_position_ms: 12345,
    });
  });

  it('shows a "noted" confirmation, never a live answer, after a successful submit', async () => {
    render(<AskTutorPanel />);
    await userEvent.type(screen.getByPlaceholderText("What's your question?"), 'Why does this work?');
    await userEvent.click(screen.getByRole('button', { name: /submit/i }));

    expect(await screen.findByText(/noted/i)).not.toBeNull();
    // D159: capture-and-log only -- there is no live AI Q&A backend. The
    // confirmation copy is explicit that no answer exists yet (the honest
    // copy itself contains the word "answer" as part of saying so) -- what
    // must NOT appear is anything that reads as a delivered answer.
    expect(screen.queryByText(/here'?s (the|your) answer/i)).toBeNull();
    expect(screen.queryByPlaceholderText("What's your question?")).toBeNull();
  });

  it('"Resume without asking" calls play() directly without submitting anything', async () => {
    render(<AskTutorPanel />);
    await userEvent.click(screen.getByRole('button', { name: /resume without asking/i }));

    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(usePlayerStore.getState().pauseReason).toBeNull();
    expect(submitTutorQuestionMock).not.toHaveBeenCalled();
  });

  it('degrades gracefully (resumes playback) if the submit call rejects', async () => {
    submitTutorQuestionMock.mockRejectedValue(new Error('network'));
    render(<AskTutorPanel />);
    await userEvent.type(screen.getByPlaceholderText("What's your question?"), 'Why does this work?');
    await userEvent.click(screen.getByRole('button', { name: /submit/i }));

    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });
});
