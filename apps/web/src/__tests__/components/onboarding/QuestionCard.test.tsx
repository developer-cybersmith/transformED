import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QuestionCard } from '@/components/onboarding/QuestionCard';
import type { Question } from '@/components/onboarding/questions';

const QUESTION: Question = {
  id: 'c1',
  dimension: 'cognitive',
  text: 'When learning something new, I prefer to:',
  options: ['Option A', 'Option B', 'Option C', 'Option D'],
};

describe('QuestionCard', () => {
  it('renders the question text and all 4 options', () => {
    render(<QuestionCard question={QUESTION} selectedIndex={undefined} onSelect={vi.fn()} />);

    expect(screen.getByText(QUESTION.text)).not.toBeNull();
    for (const option of QUESTION.options) {
      expect(screen.getByText(option)).not.toBeNull();
    }
  });

  it('calls onSelect with the correct index when an option is clicked', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<QuestionCard question={QUESTION} selectedIndex={undefined} onSelect={onSelect} />);

    await user.click(screen.getByText('Option C'));

    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it('marks the selected option as checked via role="radio"/aria-checked', () => {
    render(<QuestionCard question={QUESTION} selectedIndex={1} onSelect={vi.fn()} />);

    expect(screen.getByText('Option B').closest('button')?.getAttribute('role')).toBe('radio');
    expect(screen.getByText('Option B').closest('button')?.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('Option A').closest('button')?.getAttribute('aria-checked')).toBe('false');
  });

  it('groups the 4 options under a single radiogroup', () => {
    render(<QuestionCard question={QUESTION} selectedIndex={undefined} onSelect={vi.fn()} />);

    expect(screen.getByRole('radiogroup')).not.toBeNull();
    expect(screen.getAllByRole('radio')).toHaveLength(4);
  });

  describe('Story 2-55 accessibility (WCAG AA)', () => {
    it('ArrowDown moves selection and focus to the next option, wrapping at the end', () => {
      const onSelect = vi.fn();
      render(<QuestionCard question={QUESTION} selectedIndex={3} onSelect={onSelect} />);
      const options = screen.getAllByRole('radio');

      options[3].focus();
      fireEvent.keyDown(options[3], { key: 'ArrowDown' });

      expect(onSelect).toHaveBeenCalledWith(0);
      expect(document.activeElement).toBe(options[0]);
    });

    it('ArrowUp moves selection and focus to the previous option, wrapping at the start', () => {
      const onSelect = vi.fn();
      render(<QuestionCard question={QUESTION} selectedIndex={0} onSelect={onSelect} />);
      const options = screen.getAllByRole('radio');

      options[0].focus();
      fireEvent.keyDown(options[0], { key: 'ArrowUp' });

      expect(onSelect).toHaveBeenCalledWith(3);
      expect(document.activeElement).toBe(options[3]);
    });

    it('ArrowRight moves selection and focus to the next option (non-wrapping case)', () => {
      const onSelect = vi.fn();
      render(<QuestionCard question={QUESTION} selectedIndex={1} onSelect={onSelect} />);
      const options = screen.getAllByRole('radio');

      options[1].focus();
      fireEvent.keyDown(options[1], { key: 'ArrowRight' });

      expect(onSelect).toHaveBeenCalledWith(2);
      expect(document.activeElement).toBe(options[2]);
    });

    it('ArrowLeft moves selection and focus to the previous option (non-wrapping case)', () => {
      const onSelect = vi.fn();
      render(<QuestionCard question={QUESTION} selectedIndex={2} onSelect={onSelect} />);
      const options = screen.getAllByRole('radio');

      options[2].focus();
      fireEvent.keyDown(options[2], { key: 'ArrowLeft' });

      expect(onSelect).toHaveBeenCalledWith(1);
      expect(document.activeElement).toBe(options[1]);
    });

    it('roving tabindex: only the selected (or first, if none selected) option is a tab stop', () => {
      const { rerender } = render(<QuestionCard question={QUESTION} selectedIndex={undefined} onSelect={vi.fn()} />);
      const options = screen.getAllByRole('radio');

      expect(options[0].getAttribute('tabindex')).toBe('0');
      options.slice(1).forEach((o) => expect(o.getAttribute('tabindex')).toBe('-1'));

      rerender(<QuestionCard question={QUESTION} selectedIndex={2} onSelect={vi.fn()} />);
      const reRendered = screen.getAllByRole('radio');

      expect(reRendered[2].getAttribute('tabindex')).toBe('0');
      [0, 1, 3].forEach((idx) => expect(reRendered[idx].getAttribute('tabindex')).toBe('-1'));
    });

    it('has visible focus-ring classes on each option (inherited from the shared Button component)', () => {
      render(<QuestionCard question={QUESTION} selectedIndex={undefined} onSelect={vi.fn()} />);

      for (const option of screen.getAllByRole('radio')) {
        expect(option.className).toMatch(/focus-visible:ring-4/);
      }
    });

    it('applies the WCAG AA-compliant text-neutral-600 (not the pre-fix text-neutral-400) to the option-letter prefix', () => {
      render(<QuestionCard question={QUESTION} selectedIndex={undefined} onSelect={vi.fn()} />);

      for (const option of screen.getAllByRole('radio')) {
        const letterSpan = option.querySelector('span');
        expect(letterSpan?.className).toMatch(/text-neutral-600/);
        expect(letterSpan?.className).not.toMatch(/text-neutral-400/);
      }
    });
  });
});
