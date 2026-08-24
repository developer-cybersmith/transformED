import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProfileTab } from '@/components/settings/tabs/ProfileTab';

const { getProfileMock } = vi.hoisted(() => ({ getProfileMock: vi.fn() }));

vi.mock('@/services/settings.service', () => ({
  settingsService: { getProfile: getProfileMock },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}));

const PROFILE = {
  id: 'usr_1',
  name: 'J. Robert Oppenheimer',
  email: 'robert@example.com',
  learningGoal: 'Master Advanced Physics & Theoretical Foundations',
  academicFocus: 'Quantum Mechanics',
};

beforeEach(() => {
  getProfileMock.mockReset();
  getProfileMock.mockResolvedValue({ data: PROFILE });
});

describe('ProfileTab', () => {
  it('fetches the real profile instead of showing the hardcoded "Alex Student" identity', async () => {
    render(<ProfileTab />);

    await waitFor(() => expect(screen.getByText(PROFILE.name)).not.toBeNull());
    expect(screen.getByText(PROFILE.email)).not.toBeNull();
    expect(screen.queryByText('Alex Student')).toBeNull();
    expect(screen.queryByText('alex.student@example.com')).toBeNull();
  });

  it('shows the real learningGoal and academicFocus, not hardcoded placeholder text', async () => {
    render(<ProfileTab />);

    await waitFor(() => expect(screen.getByText(PROFILE.learningGoal)).not.toBeNull());
    expect(screen.getByText(PROFILE.academicFocus)).not.toBeNull();
    expect(screen.queryByText('Master Advanced Calculus')).toBeNull();
    expect(screen.queryByText('Mathematics & Physics')).toBeNull();
  });

  it('seeds the avatar with the profile id, never the real name or email (review fix — PII leak to a third-party CDN)', async () => {
    render(<ProfileTab />);

    await waitFor(() => expect(screen.getByText(PROFILE.name)).not.toBeNull());
    const avatar = screen.getByAltText('Profile Avatar') as HTMLImageElement;

    expect(avatar.src).toContain(encodeURIComponent(PROFILE.id));
    expect(avatar.src).not.toContain(encodeURIComponent(PROFILE.name));
    expect(avatar.src).not.toContain(encodeURIComponent(PROFILE.email));
  });

  it('shows an error state with a Retry button when the initial fetch fails, instead of loading forever (S4-10)', async () => {
    getProfileMock.mockRejectedValueOnce(new Error('network error'));
    render(<ProfileTab />);

    await waitFor(() => expect(screen.getByText(/couldn.t load your profile/i)).not.toBeNull());
    expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull();
    expect(screen.queryByText('Loading profile…')).toBeNull();
  });

  it('shows the real profile after clicking Retry following a failed fetch (S4-10)', async () => {
    getProfileMock.mockRejectedValueOnce(new Error('network error'));
    const user = userEvent.setup();
    render(<ProfileTab />);
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).not.toBeNull());

    await user.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => expect(screen.getByText(PROFILE.name)).not.toBeNull());
    expect(getProfileMock).toHaveBeenCalledTimes(2);
  });

  it('does not warn or throw when a fetch rejects after the component has unmounted (S4-10)', async () => {
    let rejectFetch!: (err: unknown) => void;
    getProfileMock.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectFetch = reject; }));
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { unmount } = render(<ProfileTab />);
    unmount();
    rejectFetch(new Error('late failure'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(consoleErrorSpy).not.toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });
});
