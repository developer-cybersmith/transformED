import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PrivacyTab } from '@/components/settings/tabs/PrivacyTab';

const { getPrivacyMock, updatePrivacyMock } = vi.hoisted(() => ({
  getPrivacyMock: vi.fn(),
  updatePrivacyMock: vi.fn(),
}));

vi.mock('@/services/settings.service', () => ({
  settingsService: {
    getPrivacy: getPrivacyMock,
    updatePrivacy: updatePrivacyMock,
  },
}));

const SETTINGS = { focusDetection: true, learningAnalytics: true, personalizedRecommendations: true };

beforeEach(() => {
  getPrivacyMock.mockReset();
  updatePrivacyMock.mockReset();
  getPrivacyMock.mockResolvedValue({ data: SETTINGS });
  updatePrivacyMock.mockResolvedValue({ data: SETTINGS });
});

describe('PrivacyTab', () => {
  it('fetches real privacy settings on mount instead of using hardcoded dummy state', async () => {
    render(<PrivacyTab />);

    await waitFor(() => expect(getPrivacyMock).toHaveBeenCalled());
  });

  it('persists a toggle change via settingsService.updatePrivacy', async () => {
    const user = userEvent.setup();
    render(<PrivacyTab />);
    await screen.findByText('Learning Analytics');

    const analyticsToggle = screen
      .getByText('Learning Analytics')
      .closest('div.flex.items-center.justify-between')
      ?.querySelector('button');
    await user.click(analyticsToggle!);

    expect(updatePrivacyMock).toHaveBeenCalledWith({ learningAnalytics: false });
  });

  it('rolls back the optimistic toggle when updatePrivacy fails', async () => {
    updatePrivacyMock.mockRejectedValue(new Error('network error'));
    const user = userEvent.setup();
    render(<PrivacyTab />);
    const analyticsToggle = (await screen.findByText('Learning Analytics'))
      .closest('div.flex.items-center.justify-between')
      ?.querySelector('button');

    await user.click(analyticsToggle!);
    await waitFor(() => expect(updatePrivacyMock).toHaveBeenCalledWith({ learningAnalytics: false }));

    await waitFor(() => expect(analyticsToggle?.getAttribute('aria-checked')).toBe('true'));
  });

  it('shows an error state with a Retry button when the initial fetch fails, instead of loading forever (S4-10)', async () => {
    getPrivacyMock.mockReset();
    getPrivacyMock.mockRejectedValueOnce(new Error('network error'));
    render(<PrivacyTab />);

    await waitFor(() => expect(screen.getByText(/couldn.t load your privacy settings/i)).not.toBeNull());
    expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull();
    expect(screen.queryByText('Loading privacy settings…')).toBeNull();
  });

  it('shows the real settings after clicking Retry following a failed fetch (S4-10)', async () => {
    getPrivacyMock.mockReset();
    getPrivacyMock.mockRejectedValueOnce(new Error('network error'));
    getPrivacyMock.mockResolvedValueOnce({ data: SETTINGS });
    const user = userEvent.setup();
    render(<PrivacyTab />);
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull());

    await user.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => expect(screen.getByText('Learning Analytics')).not.toBeNull());
    expect(getPrivacyMock).toHaveBeenCalledTimes(2);
  });

  it('does not warn or throw when a fetch rejects after the component has unmounted (S4-10)', async () => {
    getPrivacyMock.mockReset();
    let rejectFetch!: (err: unknown) => void;
    getPrivacyMock.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectFetch = reject; }));
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { unmount } = render(<PrivacyTab />);
    unmount();
    rejectFetch(new Error('late failure'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(consoleErrorSpy).not.toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });
});
