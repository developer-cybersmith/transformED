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

  it('rolls back the optimistic pace change when updatePreferences fails', async () => {
    updatePreferencesMock.mockRejectedValue(new Error('network error'));
    const user = userEvent.setup();
    render(<LearningTab />);
    await waitFor(() => expect(screen.getByText('Accelerated')).not.toBeNull());

    await user.click(screen.getByText('Moderate'));
    await waitFor(() => expect(updatePreferencesMock).toHaveBeenCalledWith({ pace: 'moderate' }));

    await waitFor(() => expect(screen.getByText('Accelerated').className).toContain('text-neutral-900'));
    expect(screen.getByText('Moderate').className).toContain('text-neutral-500');
  });

  it('shows an error state with a Retry button when the initial fetch fails, instead of loading forever (S4-10)', async () => {
    getPreferencesMock.mockReset();
    getPreferencesMock.mockRejectedValueOnce(new Error('network error'));
    render(<LearningTab />);

    await waitFor(() => expect(screen.getByText(/couldn.t load your preferences/i)).not.toBeNull());
    expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull();
    expect(screen.queryByText('Loading preferences…')).toBeNull();
  });

  it('shows the real preferences after clicking Retry following a failed fetch (S4-10)', async () => {
    getPreferencesMock.mockReset();
    getPreferencesMock.mockRejectedValueOnce(new Error('network error'));
    getPreferencesMock.mockResolvedValueOnce({ data: PREFERENCES });
    const user = userEvent.setup();
    render(<LearningTab />);
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull());

    await user.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => expect(screen.getByText('Accelerated')).not.toBeNull());
    expect(getPreferencesMock).toHaveBeenCalledTimes(2);
  });

  it('does not warn or throw when a fetch rejects after the component has unmounted (S4-10)', async () => {
    getPreferencesMock.mockReset();
    let rejectFetch!: (err: unknown) => void;
    getPreferencesMock.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectFetch = reject; }));
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { unmount } = render(<LearningTab />);
    unmount();
    rejectFetch(new Error('late failure'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(consoleErrorSpy).not.toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });
});
