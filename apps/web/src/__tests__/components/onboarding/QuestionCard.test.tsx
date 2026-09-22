import { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QuestionCard, type AnswerValue } from '@/components/onboarding/QuestionCard';
import type { Question } from '@/components/onboarding/questions';

const MCQ_QUESTION: Question = {
  id: 'q1',
  format: 'mcq',
  text: 'When learning something new, I prefer to:',
  options: ['Option A', 'Option B', 'Option C', 'Option D'],
};

const ONE_LINER_QUESTION: Question = {
  id: 'q21',
  format: 'one_liner',
  text: 'In ONE sentence, describe what you want to achieve in the next 6 months.',
  placeholder: 'In the next 6 months, I want to...',
};

const TRUE_FALSE_QUESTION: Question = {
  id: 'q26',
  format: 'true_false',
  text: 'I have abandoned at least one online course in the past 12 months.',
};

describe('QuestionCard — mcq format', () => {
  it('renders the question text and all 4 options', () => {
    render(<QuestionCard question={MCQ_QUESTION} value={undefined} onChange={vi.fn()} />);

    expect(screen.getByText(MCQ_QUESTION.text)).not.toBeNull();
    for (const option of MCQ_QUESTION.options ?? []) {
      expect(screen.getByText(option)).not.toBeNull();
    }
  });

  it('calls onChange with {format: "mcq", index} when an option is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<QuestionCard question={MCQ_QUESTION} value={undefined} onChange={onChange} />);

    await user.click(screen.getByText('Option C'));

    expect(onChange).toHaveBeenCalledWith({ format: 'mcq', index: 2 });
  });

  it('marks the selected option as checked via role="radio"/aria-checked', () => {
    const value: AnswerValue = { format: 'mcq', index: 1 };
    render(<QuestionCard question={MCQ_QUESTION} value={value} onChange={vi.fn()} />);

    expect(screen.getByText('Option B').closest('button')?.getAttribute('role')).toBe('radio');
    expect(screen.getByText('Option B').closest('button')?.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('Option A').closest('button')?.getAttribute('aria-checked')).toBe('false');
  });

  it('groups the 4 options under a single radiogroup', () => {
    render(<QuestionCard question={MCQ_QUESTION} value={undefined} onChange={vi.fn()} />);

    expect(screen.getByRole('radiogroup')).not.toBeNull();
    expect(screen.getAllByRole('radio')).toHaveLength(4);
  });

  describe('Story 2-55 accessibility (WCAG AA)', () => {
    it('ArrowDown moves selection and focus to the next option, wrapping at the end', () => {
      const onChange = vi.fn();
      const value: AnswerValue = { format: 'mcq', index: 3 };
      render(<QuestionCard question={MCQ_QUESTION} value={value} onChange={onChange} />);
      const options = screen.getAllByRole('radio');

      options[3].focus();
      fireEvent.keyDown(options[3], { key: 'ArrowDown' });

      expect(onChange).toHaveBeenCalledWith({ format: 'mcq', index: 0 });
      expect(document.activeElement).toBe(options[0]);
    });

    it('ArrowUp moves selection and focus to the previous option, wrapping at the start', () => {
      const onChange = vi.fn();
      const value: AnswerValue = { format: 'mcq', index: 0 };
      render(<QuestionCard question={MCQ_QUESTION} value={value} onChange={onChange} />);
      const options = screen.getAllByRole('radio');

      options[0].focus();
      fireEvent.keyDown(options[0], { key: 'ArrowUp' });

      expect(onChange).toHaveBeenCalledWith({ format: 'mcq', index: 3 });
      expect(document.activeElement).toBe(options[3]);
    });

    it('roving tabindex: only the selected (or first, if none selected) option is a tab stop', () => {
      const { rerender } = render(
        <QuestionCard question={MCQ_QUESTION} value={undefined} onChange={vi.fn()} />
      );
      const options = screen.getAllByRole('radio');

      expect(options[0].getAttribute('tabindex')).toBe('0');
      options.slice(1).forEach((o) => expect(o.getAttribute('tabindex')).toBe('-1'));

      rerender(
        <QuestionCard
          question={MCQ_QUESTION}
          value={{ format: 'mcq', index: 2 }}
          onChange={vi.fn()}
        />
      );
      const reRendered = screen.getAllByRole('radio');

      expect(reRendered[2].getAttribute('tabindex')).toBe('0');
      [0, 1, 3].forEach((idx) => expect(reRendered[idx].getAttribute('tabindex')).toBe('-1'));
    });

    it('has visible focus-ring classes on each option (inherited from the shared Button component)', () => {
      render(<QuestionCard question={MCQ_QUESTION} value={undefined} onChange={vi.fn()} />);

      for (const option of screen.getAllByRole('radio')) {
        expect(option.className).toMatch(/focus-visible:ring-4/);
      }
    });
  });
});

describe('QuestionCard — true_false format (Story 235)', () => {
  it('renders exactly two options, True and False', () => {
    render(<QuestionCard question={TRUE_FALSE_QUESTION} value={undefined} onChange={vi.fn()} />);

    expect(screen.getByRole('radiogroup')).not.toBeNull();
    const options = screen.getAllByRole('radio');
    expect(options).toHaveLength(2);
    expect(screen.getByText('True')).not.toBeNull();
    expect(screen.getByText('False')).not.toBeNull();
  });

  it('calls onChange with {format: "true_false", value: true} when True is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<QuestionCard question={TRUE_FALSE_QUESTION} value={undefined} onChange={onChange} />);

    await user.click(screen.getByText('True'));

    expect(onChange).toHaveBeenCalledWith({ format: 'true_false', value: true });
  });

  it('calls onChange with {format: "true_false", value: false} when False is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<QuestionCard question={TRUE_FALSE_QUESTION} value={undefined} onChange={onChange} />);

    await user.click(screen.getByText('False'));

    expect(onChange).toHaveBeenCalledWith({ format: 'true_false', value: false });
  });

  it('marks False as checked (not "unanswered") when the answer is explicitly false', () => {
    const value: AnswerValue = { format: 'true_false', value: false };
    render(<QuestionCard question={TRUE_FALSE_QUESTION} value={value} onChange={vi.fn()} />);

    expect(screen.getByText('False').closest('button')?.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('True').closest('button')?.getAttribute('aria-checked')).toBe('false');
  });

  it('reuses the roving-radio-group keyboard pattern (ArrowRight moves True -> False)', () => {
    const onChange = vi.fn();
    const value: AnswerValue = { format: 'true_false', value: true };
    render(<QuestionCard question={TRUE_FALSE_QUESTION} value={value} onChange={onChange} />);
    const options = screen.getAllByRole('radio');

    options[0].focus();
    fireEvent.keyDown(options[0], { key: 'ArrowRight' });

    expect(onChange).toHaveBeenCalledWith({ format: 'true_false', value: false });
    expect(document.activeElement).toBe(options[1]);
  });
});

describe('QuestionCard — one_liner format (Story 235)', () => {
  it('renders a textarea with the question placeholder', () => {
    render(<QuestionCard question={ONE_LINER_QUESTION} value={undefined} onChange={vi.fn()} />);

    const textarea = screen.getByPlaceholderText(ONE_LINER_QUESTION.placeholder ?? '');
    expect(textarea.tagName).toBe('TEXTAREA');
  });

  it('calls onChange with {format: "one_liner", text} on each keystroke', async () => {
    // QuestionCard is a fully controlled component (text comes from `value`, not
    // internal state) -- since this test never feeds onChange's output back in as
    // a new `value` prop, each keystroke fires against the still-empty controlled
    // value, so onChange receives one character per call, not the accumulated
    // string. A real caller (OnboardingFlow.tsx) re-renders with the new value
    // after each onChange, which is what actually accumulates "Hi" in production.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<QuestionCard question={ONE_LINER_QUESTION} value={undefined} onChange={onChange} />);

    await user.type(screen.getByPlaceholderText(ONE_LINER_QUESTION.placeholder ?? ''), 'Hi');

    expect(onChange).toHaveBeenCalledWith({ format: 'one_liner', text: 'H' });
    expect(onChange).toHaveBeenCalledWith({ format: 'one_liner', text: 'i' });
  });

  it('accumulates typed text correctly when the parent feeds onChange back into value (controlled round-trip)', async () => {
    function ControlledWrapper() {
      const [value, setValue] = useState<AnswerValue | undefined>(undefined);
      return (
        <QuestionCard question={ONE_LINER_QUESTION} value={value} onChange={setValue} />
      );
    }
    const user = userEvent.setup();
    render(<ControlledWrapper />);

    await user.type(screen.getByPlaceholderText(ONE_LINER_QUESTION.placeholder ?? ''), 'Hi');

    const textarea = screen.getByPlaceholderText(
      ONE_LINER_QUESTION.placeholder ?? ''
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Hi');
  });

  it('enforces the 1000-char cap (matches the backend response_text max_length)', () => {
    render(<QuestionCard question={ONE_LINER_QUESTION} value={undefined} onChange={vi.fn()} />);

    const textarea = screen.getByPlaceholderText(ONE_LINER_QUESTION.placeholder ?? '');
    expect(textarea.getAttribute('maxlength')).toBe('1000');
  });

  it('shows a live character counter reflecting the current text length', () => {
    const value: AnswerValue = { format: 'one_liner', text: 'Pass my exam' };
    render(<QuestionCard question={ONE_LINER_QUESTION} value={value} onChange={vi.fn()} />);

    expect(screen.getByText('12/1000')).not.toBeNull();
  });

  it('shows 0/1000 when unanswered', () => {
    render(<QuestionCard question={ONE_LINER_QUESTION} value={undefined} onChange={vi.fn()} />);

    expect(screen.getByText('0/1000')).not.toBeNull();
  });
});
