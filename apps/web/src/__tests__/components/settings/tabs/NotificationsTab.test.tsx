import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NotificationsTab } from '@/components/settings/tabs/NotificationsTab';

const { useNotificationPreferencesMock } = vi.hoisted(() => ({
  useNotificationPreferencesMock: vi.fn(),
}));

vi.mock('@/hooks/useNotificationPreferences', () => ({
  useNotificationPreferences: useNotificationPreferencesMock,
}));

const ALL_TRUE = {
  session_report_email: true,
  lesson_ready_email: true,
  weekly_progress_email: true,
  streak_reminders: true,
};

function baseHookReturn(overrides: Partial<ReturnType<typeof useNotificationPreferencesMock>> = {}) {
  return {
    preferences: ALL_TRUE,
    isLoading: false,
    updatePreference: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function toggleFor(label: string) {
  return screen.getByText(label).closest('div.flex.items-center.justify-between')?.querySelector('button');
}

beforeEach(() => {
  useNotificationPreferencesMock.mockReset();
  useNotificationPreferencesMock.mockReturnValue(baseHookReturn());
});

describe('NotificationsTab (S3-07 AC-1)', () => {
  it('shows a loading state while preferences are loading', () => {
    useNotificationPreferencesMock.mockReturnValue(baseHookReturn({ isLoading: true }));
    render(<NotificationsTab />);

    expect(screen.getByText(/loading notification settings/i)).not.toBeNull();
  });

  it('renders all four real toggles, including the new Session Report one', () => {
    render(<NotificationsTab />);

    expect(screen.getByText('Session Report')).not.toBeNull();
    expect(screen.getByText('Lesson Ready')).not.toBeNull();
    expect(screen.getByText('Weekly Progress')).not.toBeNull();
    expect(screen.getByText('Streak Reminders')).not.toBeNull();
  });

  it('reflects real false values from the hook, not a hardcoded default', () => {
    useNotificationPreferencesMock.mockReturnValue(
      baseHookReturn({ preferences: { ...ALL_TRUE, streak_reminders: false } })
    );
    render(<NotificationsTab />);

    expect(toggleFor('Streak Reminders')?.getAttribute('aria-checked')).toBe('false');
    expect(toggleFor('Lesson Ready')?.getAttribute('aria-checked')).toBe('true');
  });

  it('calls updatePreference with the flipped value when a toggle is clicked', async () => {
    const updatePreference = vi.fn().mockResolvedValue(undefined);
    useNotificationPreferencesMock.mockReturnValue(baseHookReturn({ updatePreference }));
    const user = userEvent.setup();
    render(<NotificationsTab />);

    await user.click(toggleFor('Lesson Ready')!);

    expect(updatePreference).toHaveBeenCalledWith('lesson_ready_email', false);
  });

  it('calls updatePreference for the new Session Report toggle with its real field name', async () => {
    const updatePreference = vi.fn().mockResolvedValue(undefined);
    useNotificationPreferencesMock.mockReturnValue(baseHookReturn({ updatePreference }));
    const user = userEvent.setup();
    render(<NotificationsTab />);

    await user.click(toggleFor('Session Report')!);

    expect(updatePreference).toHaveBeenCalledWith('session_report_email', false);
  });
});
