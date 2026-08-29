import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
  // A real sessionId is the realistic default (mintSession has already
  // resolved by the time a student reaches the quiz in normal use) -- tests
  // that specifically care about the empty-sessionId guard override this.
  usePlayerStore.setState({ status: 'QUIZ', currentSegmentIndex: 0, sessionId: 'sess_42' });
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
      await userEvent.click(screen.getByText(THREE_QUESTIONS[i].options[i]));
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

  it('does not call the API when sessionId is still empty (mintSession has not resolved yet)', async () => {
    // Bug fix: session_id='' reaches Postgres as a real 500 (22P02 invalid
    // input syntax for type uuid) if this call is ever attempted.
    usePlayerStore.setState({ sessionId: '' });
    render(<QuizOverlay questions={QUESTIONS} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await userEvent.click(screen.getByText(QUESTIONS[1].options[1]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    expect(submitQuizMock).not.toHaveBeenCalled();
  });

  it('shows the score summary feedback using the real backend field names (is_correct/explanation, not correct/message) (S2-11 review fix)', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    // result (and its feedback list) renders once submitQuiz resolves, on the
    // last question's Submit -- no need to click Continue to see it.
    await waitFor(() => expect(screen.getByText('Nice work.')).not.toBeNull());
  });

  it('styles score summary feedback by is_correct -- emerald for correct, red for incorrect (review fix)', async () => {
    submitQuizMock.mockResolvedValue({
      session_id: 'sess_1', score: 50, correct_count: 1, total_count: 2, ces_contribution: 0.1,
      feedback: [
        {
          question_id: 'q_1', question: QUESTIONS[0].question, is_correct: true,
          correct_index: 0, correct_option: QUESTIONS[0].options[0],
          selected_option: QUESTIONS[0].options[0], explanation: 'Correct feedback.',
        },
        {
          question_id: 'q_2', question: QUESTIONS[1].question, is_correct: false,
          correct_index: 1, correct_option: QUESTIONS[1].options[1],
          selected_option: QUESTIONS[1].options[0], explanation: 'Incorrect feedback.',
        },
      ],
    });
    render(<QuizOverlay questions={QUESTIONS} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await userEvent.click(screen.getByText(QUESTIONS[1].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    await waitFor(() => {
      expect(screen.getByText('Correct feedback.').className).toMatch(/text-emerald-700/);
      expect(screen.getByText('Incorrect feedback.').className).toMatch(/text-red-700/);
    });
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

describe('QuizOverlay — Story 2-55 accessibility (WCAG AA)', () => {
  it('groups options under a single radiogroup with role="radio"/aria-checked per option', () => {
    render(<QuizOverlay questions={QUESTIONS} />);

    expect(screen.getByRole('radiogroup')).not.toBeNull();
    const options = screen.getAllByRole('radio');
    expect(options).toHaveLength(QUESTIONS[0].options.length);
    expect(options.every((el) => el.getAttribute('aria-checked') === 'false')).toBe(true);
  });

  it('has visible focus-ring classes on option, Submit, and Next buttons', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    for (const option of screen.getAllByRole('radio')) {
      expect(option.className).toMatch(/focus-visible:ring-4/);
    }
    expect(screen.getByRole('button', { name: 'Submit' }).className).toMatch(/focus-visible:ring-4/);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(screen.getByRole('button', { name: 'Continue' }).className).toMatch(/focus-visible:ring-4/);
  });

  it('announces correct/incorrect feedback via role="status" aria-live="polite"', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    const status = screen.getByRole('status');
    expect(status.getAttribute('aria-live')).toBe('polite');
    expect(status.textContent).toContain('Correct!');
  });

  it('the status region is always mounted (present, empty) before submit -- a content MUTATION on submit, not a fresh node insertion', async () => {
    // Some screen reader/browser combinations only announce aria-live
    // changes on an already-present node, not a newly-inserted one
    // (review fix, S4-04).
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    const statusBefore = screen.getByRole('status');
    expect(statusBefore.textContent).toBe('');

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    const statusAfter = screen.getByRole('status');
    expect(statusAfter).toBe(statusBefore);
    expect(statusAfter.textContent).toContain('Correct!');
  });

  it('applies the WCAG AA-compliant text-neutral-600 (not the pre-fix text-neutral-400) to the option-letter prefix and the post-submit dimmed option text', async () => {
    render(<QuizOverlay questions={QUESTIONS} />);

    for (const option of screen.getAllByRole('radio')) {
      const letterSpan = option.querySelector('span');
      expect(letterSpan?.className).toMatch(/text-neutral-600/);
      expect(letterSpan?.className).not.toMatch(/text-neutral-400/);
    }

    // QUESTIONS[0].correct_index is 0; select and submit the wrong answer
    // (index 1) so a non-correct, non-selected option (index 2 or 3) renders
    // in the post-submit "dimmed" branch of optionStyle().
    await userEvent.click(screen.getByText(QUESTIONS[0].options[1]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    const dimmedOption = screen.getAllByRole('radio')[3];
    expect(dimmedOption.className).toMatch(/text-neutral-600/);
    expect(dimmedOption.className).not.toMatch(/text-neutral-400/);
  });

  it('ArrowDown/ArrowRight move selection and focus to the next option, wrapping at the end', () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);
    const options = screen.getAllByRole('radio');

    options[0].focus();
    fireEvent.keyDown(options[0], { key: 'ArrowDown' });
    expect(options[1].getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(options[1]);

    // Wrap from the last option back to the first.
    options[3].focus();
    fireEvent.keyDown(options[3], { key: 'ArrowRight' });
    expect(options[0].getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(options[0]);
  });

  it('ArrowUp/ArrowLeft move selection and focus to the previous option, wrapping at the start', () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);
    const options = screen.getAllByRole('radio');

    // Wrap from the first option back to the last.
    options[0].focus();
    fireEvent.keyDown(options[0], { key: 'ArrowUp' });
    expect(options[3].getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(options[3]);

    fireEvent.keyDown(options[3], { key: 'ArrowLeft' });
    expect(options[2].getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(options[2]);
  });

  it('roving tabindex: only the selected (or first, if none selected) option is a tab stop', () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);
    const options = screen.getAllByRole('radio');

    expect(options[0].getAttribute('tabindex')).toBe('0');
    options.slice(1).forEach((o) => expect(o.getAttribute('tabindex')).toBe('-1'));

    fireEvent.keyDown(options[0], { key: 'ArrowDown' });
    expect(options[1].getAttribute('tabindex')).toBe('0');
    expect(options[0].getAttribute('tabindex')).toBe('-1');
  });

  it('ignores arrow keys once the question is submitted', async () => {
    render(<QuizOverlay questions={[QUESTIONS[0]]} />);

    await userEvent.click(screen.getByText(QUESTIONS[0].options[0]));
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));

    const submittedOptions = screen.getAllByRole('radio');
    fireEvent.keyDown(submittedOptions[0], { key: 'ArrowDown' });
    expect(submittedOptions[0].getAttribute('aria-checked')).toBe('true');
    expect(submittedOptions[1].getAttribute('aria-checked')).toBe('false');
  });
});
