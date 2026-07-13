import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NotificationsTab } from '@/components/settings/tabs/NotificationsTab';

const { getNotificationsMock, updateNotificationsMock } = vi.hoisted(() => ({
  getNotificationsMock: vi.fn(),
  updateNotificationsMock: vi.fn(),
}));

vi.mock('@/services/settings.service', () => ({
  settingsService: {
    getNotifications: getNotificationsMock,
    updateNotifications: updateNotificationsMock,
  },
}));

const SETTINGS = { lessonReady: true, weeklyProgress: true, streakReminders: false };

beforeEach(() => {
  getNotificationsMock.mockReset();
  updateNotificationsMock.mockReset();
  getNotificationsMock.mockResolvedValue({ data: SETTINGS });
  updateNotificationsMock.mockResolvedValue({ data: SETTINGS });
});

describe('NotificationsTab', () => {
  it('fetches real notification settings on mount instead of using hardcoded dummy state', async () => {
    render(<NotificationsTab />);

    await waitFor(() => expect(getNotificationsMock).toHaveBeenCalled());
  });

  it('reflects the real streakReminders=false value from the fetched settings, not the hardcoded default', async () => {
    render(<NotificationsTab />);
    await waitFor(() => expect(getNotificationsMock).toHaveBeenCalled());

    const streakToggle = await screen.findByText('Streak Reminders');
    const toggleButton = streakToggle.closest('div.flex.items-center.justify-between')?.querySelector('button');
    await waitFor(() => expect(toggleButton?.getAttribute('aria-checked')).toBe('false'));
  });

  it('does not render "Product Updates" — there is no corresponding field in NotificationSettings', async () => {
    render(<NotificationsTab />);
    await waitFor(() => expect(getNotificationsMock).toHaveBeenCalled());

    expect(screen.queryByText('Product Updates')).toBeNull();
  });

  it('persists a toggle change via settingsService.updateNotifications', async () => {
    const user = userEvent.setup();
    render(<NotificationsTab />);
    await screen.findByText('Lesson Ready');

    const lessonReadyToggle = screen.getByText('Lesson Ready').closest('div.flex.items-center.justify-between')?.querySelector('button');
    await user.click(lessonReadyToggle!);

    expect(updateNotificationsMock).toHaveBeenCalledWith({ lessonReady: false });
  });

  it('rolls back the optimistic toggle when updateNotifications fails', async () => {
    updateNotificationsMock.mockRejectedValue(new Error('network error'));
    const user = userEvent.setup();
    render(<NotificationsTab />);
    const lessonReadyToggle = (await screen.findByText('Lesson Ready'))
      .closest('div.flex.items-center.justify-between')
      ?.querySelector('button');

    await user.click(lessonReadyToggle!);
    await waitFor(() => expect(updateNotificationsMock).toHaveBeenCalledWith({ lessonReady: false }));

    await waitFor(() => expect(lessonReadyToggle?.getAttribute('aria-checked')).toBe('true'));
  });
});
