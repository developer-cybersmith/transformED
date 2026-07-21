import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Sidebar } from '@/components/dashboard/shell/Sidebar';

const { logoutMock } = vi.hoisted(() => ({ logoutMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: logoutMock }),
}));

beforeEach(() => {
  logoutMock.mockReset();
});

describe('Sidebar — Account menu', () => {
  it('opens the menu on click', async () => {
    const user = userEvent.setup();
    render(<Sidebar />);

    await user.click(screen.getByRole('button', { name: /account/i }));

    expect(screen.getByText('Sign Out')).not.toBeNull();
  });

  it('closes the menu on Escape (review fix — keyboard dismissal)', async () => {
    const user = userEvent.setup();
    render(<Sidebar />);

    await user.click(screen.getByRole('button', { name: /account/i }));
    expect(screen.getByText('Sign Out')).not.toBeNull();

    fireEvent.keyDown(document, { key: 'Escape' });

    // AnimatePresence's exit animation removes the DOM node asynchronously.
    await waitFor(() => expect(screen.queryByText('Sign Out')).toBeNull());
  });
});
