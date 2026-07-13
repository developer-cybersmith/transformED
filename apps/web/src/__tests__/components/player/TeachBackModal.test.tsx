import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TeachBackModal } from '@/components/player/TeachBackModal';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

const { submitTeachBackMock } = vi.hoisted(() => ({
  submitTeachBackMock: vi.fn(),
}));

vi.mock('@/lib/assessment', () => ({
  submitTeachBack: submitTeachBackMock,
}));

const RESULT = {
  session_id: 'sess_1',
  rubric_scores: { accuracy: 80, completeness: 60, clarity: 90 },
  overall_score: 76,
  ces_contribution: 0.1,
  feedback: 'Nice explanation of the core idea!',
};

beforeEach(() => {
  submitTeachBackMock.mockReset();
  submitTeachBackMock.mockResolvedValue(RESULT);
  usePlayerStore.getState().loadLesson(mockLessonPackage);
  usePlayerStore.setState({ status: 'TEACH_BACK', currentSegmentIndex: 0 });
});

function renderModal() {
  return render(<TeachBackModal prompt="Explain SQL injection in your own words." segmentTitle="What is SQL Injection?" />);
}

describe('TeachBackModal', () => {
  it('renders the prompt and segment title', () => {
    renderModal();
    expect(screen.getByText('Explain SQL injection in your own words.')).not.toBeNull();
    expect(screen.getByText('What is SQL Injection?')).not.toBeNull();
  });

  it('has no timer element of any kind', () => {
    const { container } = renderModal();
    expect(container.textContent).not.toMatch(/\d+:\d{2}/); // mm:ss style countdown
    expect(screen.queryByRole('timer')).toBeNull();
  });

  it('auto-focuses the textarea on open', () => {
    renderModal();
    expect(document.activeElement).toBe(screen.getByPlaceholderText('Type your explanation here…'));
  });

  it('disables submit until text is entered', async () => {
    renderModal();
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It breaks the query.');
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('labels the submit button "Submit & Continue"', () => {
    renderModal();
    expect(screen.getByRole('button', { name: 'Submit & Continue' })).not.toBeNull();
  });

  it('Skip calls exitTeachBack without submitting', async () => {
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.click(screen.getByText('Skip'));

    expect(exitTeachBack).toHaveBeenCalled();
    expect(submitTeachBackMock).not.toHaveBeenCalled();
  });

  it('submits the trimmed response text with session/lesson/segment ids', async () => {
    usePlayerStore.setState({ sessionId: 'sess_42' });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), '  It terminates the query early.  ');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() =>
      expect(submitTeachBackMock).toHaveBeenCalledWith({
        session_id: 'sess_42',
        lesson_id: mockLessonPackage.lesson_id,
        segment_id: mockLessonPackage.segments[0].segment_id,
        response_text: 'It terminates the query early.',
      })
    );
  });

  it('shows an encouraging message after scoring — never a numeric score or rubric breakdown', async () => {
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() => expect(screen.getByText(RESULT.feedback)).not.toBeNull());

    // No numeric score/percentage anywhere in the result view
    expect(screen.queryByText(/\d+%/)).toBeNull();
    expect(screen.queryByText(String(RESULT.overall_score))).toBeNull();
    // No rubric dimension breakdown shown to the student
    expect(screen.queryByText(/accuracy/i)).toBeNull();
    expect(screen.queryByText(/completeness/i)).toBeNull();
    expect(screen.queryByText(/clarity/i)).toBeNull();
  });

  it('Continue after scoring calls exitTeachBack', async () => {
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));
    await waitFor(() => expect(screen.getByText(RESULT.feedback)).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(exitTeachBack).toHaveBeenCalled();
  });

  it('does not block the student when the API call fails — exits teach-back gracefully', async () => {
    submitTeachBackMock.mockRejectedValue(new Error('network error'));
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() => expect(exitTeachBack).toHaveBeenCalled());
  });
});
