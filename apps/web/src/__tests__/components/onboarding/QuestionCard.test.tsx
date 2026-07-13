import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
