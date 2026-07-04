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
});
