import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ProfileTab } from '@/components/settings/tabs/ProfileTab';

const { getProfileMock } = vi.hoisted(() => ({ getProfileMock: vi.fn() }));

vi.mock('@/services/settings.service', () => ({
  settingsService: { getProfile: getProfileMock },
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
});
