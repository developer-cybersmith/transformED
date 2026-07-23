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

// Realistic tier-aware fixture (S2-11 / Story 3-28): 3 questions for one
// segment, using the real quiz_{segment_id}_{index} id format instead of the
// placeholder q_1/q_2 -- the id must round-trip unparsed regardless of shape.
const THREE_QUESTIONS: QuizQuestion[] = [
  {
    question_id: 'quiz_section_2_6_0',
    type: 'mcq',
    question: 'Question one?',
    options: ['A', 'B', 'C', 'D'],
    correct_index: 0,
    explanation: 'Explanation one.',
    difficulty: 'medium',
  },
  {
    question_id: 'quiz_section_2_6_1',
    type: 'mcq',
    question: 'Question two?',
    options: ['A', 'B', 'C', 'D'],
    correct_index: 1,
    explanation: 'Explanation two.',
    difficulty: 'medium',
  },
  {
    question_id: 'quiz_section_2_6_2',
    type: 'mcq',
    question: 'Question three?',
    options: ['A', 'B', 'C', 'D'],
    correct_index: 2,
    explanation: 'Explanation three.',
    difficulty: 'medium',
  },
];

const RESULT = {
  session_id: 'sess_1',
  score: 100,
  correct_count: 2,
  total_count: 2,
  ces_contribution: 0.2,
  // Real backend shape (apps/api/app/modules/assessment/service.py::grade_quiz)
  // -- is_correct/explanation, not correct/message (review-motivated fix, S2-11).
  feedback: [
    {
      question_id: 'q_1', question: QUESTIONS[0].question, is_correct: true,
      correct_index: 0, correct_option: QUESTIONS[0].options[0],
      selected_option: QUESTIONS[0].options[0], explanation: 'Nice work.',
    },
    {
      question_id: 'q_2', question: QUESTIONS[1].question, is_correct: true,
      correct_index: 1, correct_option: QUESTIONS[1].options[1],
      selected_option: QUESTIONS[1].options[1], explanation: 'Exactly right.',
    },
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

  it('handles a 3-question segment (T1-tier count) with realistic quiz_{segment_id}_{index} ids, submitting all 3 unparsed (S2-11 / Story 3-28 confirmation)', async () => {
    usePlayerStore.setState({ sessionId: 'sess_42' });
    render(<QuizOverlay questions={THREE_QUESTIONS} />);

    expect(screen.getByText('1 / 3')).not.toBeNull();

    for (let i = 0; i < THREE_QUESTIONS.length; i++) {
      await userEvent.click(screen.getByText(THREE_QUESTIONS[i].options[i % 4]));
      await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
      if (i < THREE_QUESTIONS.length - 1) {
        await userEvent.click(screen.getByRole('button', { name: 'Next question' }));
      }
    }

    await waitFor(() =>
      expect(submitQuizMock).toHaveBeenCalledWith(
        expect.objectContaining({
          answers: [
            { question_id: 'quiz_section_2_6_0', response_index: 0, response_time_ms: expect.any(Number) },
            { question_id: 'quiz_section_2_6_1', response_index: 1, response_time_ms: expect.any(Number) },
            { question_id: 'quiz_section_2_6_2', response_index: 2, response_time_ms: expect.any(Number) },
          ],
        })
      )
    );
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

  it('shows the score summary feedback using the real backend field names (is_correct/explanation, not correct/message) (S2-11 review fix)', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    // result (and its feedback list) renders once submitQuiz resolves, on the
    // last question's Submit -- no need to click Continue to see it.
    await waitFor(() => expect(screen.getByText('Nice work.')).not.toBeNull());
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
