import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AccountTab } from '@/components/settings/tabs/AccountTab';

const { logoutMock } = vi.hoisted(() => ({ logoutMock: vi.fn() }));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: logoutMock }),
}));

beforeEach(() => {
  logoutMock.mockReset();
});

describe('AccountTab', () => {
  it('renders all actions as real, keyboard-focusable buttons', () => {
    render(<AccountTab />);

    for (const label of ['Upgrade to Premium', 'Change Password', 'Sign Out', 'Delete Account']) {
      const button = screen.getByText(label).closest('button');
      expect(button).not.toBeNull();
      expect(button?.tagName).toBe('BUTTON');
    }
  });

  it('calls logout when "Sign Out" is clicked', async () => {
    const user = userEvent.setup();
    render(<AccountTab />);

    await user.click(screen.getByText('Sign Out'));

    expect(logoutMock).toHaveBeenCalled();
  });
});
