import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DNAResultCard } from '@/components/onboarding/DNAResultCard';
import type { OnboardingResult } from '@/types/assessment';

const RESULT: OnboardingResult = {
  badge_labels: ['Pattern Thinker', 'Goal-Oriented'],
  profile_text:
    'You tend to learn visually and set clear goals for yourself. This assessment reflects your personal ' +
    'learning preferences, not your intelligence or capability. — Pursuant to DPDP Act 2023.',
  session_count: 0,
};

describe('DNAResultCard', () => {
  it('renders every badge label', () => {
    render(<DNAResultCard result={RESULT} onContinue={vi.fn()} />);
    for (const label of RESULT.badge_labels) {
      expect(screen.getByText(label)).not.toBeNull();
    }
  });

  it('renders profile_text in full, including the trailing DPDP disclaimer sentence', () => {
    render(<DNAResultCard result={RESULT} onContinue={vi.fn()} />);
    expect(screen.getByText(RESULT.profile_text)).not.toBeNull();
  });

  it('never renders any raw numeric dimension-score field name', () => {
    render(<DNAResultCard result={RESULT} onContinue={vi.fn()} />);
    const forbidden = [
      'pattern_recognition', 'logical_deduction', 'processing_speed',
      'frustration_tolerance', 'persistence', 'help_seeking',
      'goal_orientation', 'curiosity_index', 'study_independence',
    ];
    const bodyText = document.body.textContent ?? '';
    for (const field of forbidden) {
      expect(bodyText).not.toContain(field);
    }
  });

  it('calls onContinue when the continue button is clicked', async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<DNAResultCard result={RESULT} onContinue={onContinue} />);

    await user.click(screen.getByRole('button'));

    expect(onContinue).toHaveBeenCalled();
  });
});
