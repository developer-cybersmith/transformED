import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ModeSelection } from '@/components/dashboard/upload/ModeSelection';
import { LEARNER_TIER_OPTIONS } from '@/types/learnerMode';

describe('ModeSelection', () => {
  it('renders exactly 3 tier cards as real, keyboard-focusable buttons with label and description', () => {
    render(<ModeSelection onSelect={vi.fn()} />);

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(3);

    for (const option of LEARNER_TIER_OPTIONS) {
      expect(screen.getByText(option.label)).not.toBeNull();
      expect(screen.getByText(option.description)).not.toBeNull();
    }
  });

  it('clicking the Deep card calls onSelect with "deep" exactly once', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ModeSelection onSelect={onSelect} />);

    await user.click(screen.getByText('Deep').closest('button')!);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('deep');
  });

  it('clicking the Balanced card calls onSelect with "balanced" exactly once', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ModeSelection onSelect={onSelect} />);

    await user.click(screen.getByText('Balanced').closest('button')!);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('balanced');
  });

  it('clicking the Refresher card calls onSelect with "refresher" exactly once', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ModeSelection onSelect={onSelect} />);

    await user.click(screen.getByText('Refresher').closest('button')!);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('refresher');
  });

  it('every card has a visible focus-visible ring for keyboard users', () => {
    render(<ModeSelection onSelect={vi.fn()} />);

    for (const button of screen.getAllByRole('button')) {
      expect(button.className).toMatch(/focus-visible:ring/);
    }
  });

  it('moves focus to the first card on mount, so keyboard users land on the screen without re-tabbing', () => {
    render(<ModeSelection onSelect={vi.fn()} />);

    expect(document.activeElement).toBe(screen.getByText('Deep').closest('button'));
  });
});
