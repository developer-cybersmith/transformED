import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QuizOverlay } from '@/components/player/QuizOverlay';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';
import type { QuizQuestion } from '@hie/shared/types/lesson';

const { submitQuizMock } = vi.hoisted(() => ({
  submitQuizMock: vi.fn(),
}));

vi.mock('@/lib/assessment', () => ({
  submitQuiz: submitQuizMock,
}));

const QUESTIONS: QuizQuestion[] = [
  {
    question_id: 'q_1',
    type: 'mcq',
    question: 'What character commonly triggers a SQL injection crash?',
    options: ["Single quote (')", 'Semicolon (;)', 'Percent (%)', 'Hash (#)'],
    correct_index: 0,
    explanation: "A trailing quote terminates the string literal early, breaking the query.",
    difficulty: 'medium',
  },
  {
    question_id: 'q_2',
    type: 'mcq',
    question: 'Why does the crash prove the app is vulnerable?',
    options: ['It does not', 'Input reached the SQL string unsanitized', 'The server rebooted', 'The login worked'],
    correct_index: 1,
    explanation: 'Unsanitized input reaching the query string is the root cause.',
    difficulty: 'medium',
  },
];

const RESULT = {
  session_id: 'sess_1',
  score: 100,
  correct_count: 2,
  total_count: 2,
  ces_contribution: 0.2,
  feedback: [
    { question_id: 'q_1', correct: true, message: 'Nice work.' },
    { question_id: 'q_2', correct: true, message: 'Exactly right.' },
  ],
};

beforeEach(() => {
  submitQuizMock.mockReset();
  submitQuizMock.mockResolvedValue(RESULT);
  usePlayerStore.getState().loadLesson(mockLessonPackage);
  usePlayerStore.setState({ status: 'QUIZ', currentSegmentIndex: 0 });
});

describe('QuizOverlay', () => {
  it('renders the first question and its options', () => {
    render(<QuizOverlay questions={QUESTIONS} />);
    expect(screen.getByText(QUESTIONS[0].question)).not.toBeNull();
    QUESTIONS[0].options.forEach((opt) => expect(screen.getByText(opt)).not.toBeNull());
  });

  it('has no timer element of any kind', () => {
    const { container } = render(<QuizOverlay questions={QUESTIONS} />);
    expect(container.textContent).not.toMatch(/\d+:\d{2}/);
    expect(screen.queryByRole('timer')).toBeNull();
  });

  it('disables submit until an option is selected', async () => {
    render(<QuizOverlay questions={QUESTIONS} />);
    expect((screen.getByRole('button', { name: 'Submit' }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    expect((screen.getByRole('button', { name: 'Submit' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows correct/incorrect feedback with the explanation after submit', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    expect(screen.getByText('Correct!')).not.toBeNull();
    expect(screen.getByText(QUESTIONS[0].explanation)).not.toBeNull();
  });

  it('always shows Continue after the last question, regardless of correctness', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[1])); // wrong answer
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    expect(screen.getByText('Not quite.')).not.toBeNull();
    await waitFor(() => expect((screen.getByRole('button', { name: 'Continue' }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('advances to the next question and resets selection state', async () => {
    render(<QuizOverlay questions={QUESTIONS} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Next question' }));

    expect(screen.getByText(QUESTIONS[1].question)).not.toBeNull();
    expect((screen.getByRole('button', { name: 'Submit' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('submits all collected answers with session/lesson/segment ids on the last question', async () => {
    usePlayerStore.setState({ sessionId: 'sess_42' });
    render(<QuizOverlay questions={QUESTIONS} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await userEvent.click(screen.getByText(QUESTIONS[1].options[1]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    await waitFor(() =>
      expect(submitQuizMock).toHaveBeenCalledWith({
        session_id: 'sess_42',
        lesson_id: mockLessonPackage.lesson_id,
        segment_id: mockLessonPackage.segments[0].segment_id,
        answers: [
          { question_id: 'q_1', response_index: 0, response_time_ms: expect.any(Number) },
          { question_id: 'q_2', response_index: 1, response_time_ms: expect.any(Number) },
        ],
      })
    );
  });

  it('Continue exits the quiz even when the API call fails — never blocks progress', async () => {
    submitQuizMock.mockRejectedValue(new Error('network error'));
    const exitQuiz = vi.fn();
    usePlayerStore.setState({ exitQuiz });
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Continue' }) as HTMLButtonElement).disabled).toBe(false));

    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(exitQuiz).toHaveBeenCalled();
  });
});
