import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LearningTab } from '@/components/settings/tabs/LearningTab';

const { getPreferencesMock, updatePreferencesMock } = vi.hoisted(() => ({
  getPreferencesMock: vi.fn(),
  updatePreferencesMock: vi.fn(),
}));

vi.mock('@/services/settings.service', () => ({
  settingsService: {
    getPreferences: getPreferencesMock,
    updatePreferences: updatePreferencesMock,
  },
}));

const PREFERENCES = {
  pace: 'accelerated',
  interventionFrequency: 'medium',
  explanationStyle: 'socratic',
  learningStyle: 'visual',
};

beforeEach(() => {
  getPreferencesMock.mockReset();
  updatePreferencesMock.mockReset();
  getPreferencesMock.mockResolvedValue({ data: PREFERENCES });
  updatePreferencesMock.mockResolvedValue({ data: PREFERENCES });
});

describe('LearningTab', () => {
  it('fetches real preferences on mount instead of using hardcoded dummy state', async () => {
    render(<LearningTab />);

    await waitFor(() => expect(getPreferencesMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText('Accelerated')).not.toBeNull());
  });

  it('renders the real enum options, not the old non-existent ones (Intensive/Simple/Technical/Minimal/Active/Conceptual/Hands-on)', async () => {
    render(<LearningTab />);
    await waitFor(() => expect(screen.getByText('Accelerated')).not.toBeNull());

    for (const stale of ['Intensive', 'Simple', 'Technical', 'Minimal', 'Active', 'Conceptual', 'Hands-on']) {
      expect(screen.queryByText(stale)).toBeNull();
    }
    for (const real of ['Relaxed', 'Moderate', 'Accelerated', 'Concise', 'Detailed', 'Socratic', 'Low', 'Medium', 'High', 'Visual', 'Auditory', 'Kinesthetic', 'Reading']) {
      expect(screen.getByText(real)).not.toBeNull();
    }
  });

  it('persists a pace change via settingsService.updatePreferences with the correct real enum value', async () => {
    const user = userEvent.setup();
    render(<LearningTab />);
    await waitFor(() => expect(screen.getByText('Moderate')).not.toBeNull());

    await user.click(screen.getByText('Moderate'));

    expect(updatePreferencesMock).toHaveBeenCalledWith({ pace: 'moderate' });
  });
});
