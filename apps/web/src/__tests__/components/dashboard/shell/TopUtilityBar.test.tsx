import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TopUtilityBar } from '@/components/dashboard/shell/TopUtilityBar';

const { logoutMock } = vi.hoisted(() => ({ logoutMock: vi.fn() }));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'usr_1', full_name: 'J. Robert Oppenheimer', email: 'robert@example.com' },
    logout: logoutMock,
  }),
}));

beforeEach(() => {
  logoutMock.mockReset();
});

describe('TopUtilityBar — profile menu', () => {
  it('opens the menu on click, showing the display name and email', async () => {
    const user = userEvent.setup();
    render(<TopUtilityBar />);

    await user.click(screen.getByRole('button', { name: /profile/i }));

    expect(screen.getByText('J. Robert Oppenheimer')).not.toBeNull();
    expect(screen.getByText('robert@example.com')).not.toBeNull();
  });

  it('closes the menu on Escape (review fix — keyboard dismissal)', async () => {
    const user = userEvent.setup();
    render(<TopUtilityBar />);

    await user.click(screen.getByRole('button', { name: /profile/i }));
    expect(screen.getByText('Sign Out')).not.toBeNull();

    fireEvent.keyDown(document, { key: 'Escape' });

    // AnimatePresence's exit animation removes the DOM node asynchronously.
    await waitFor(() => expect(screen.queryByText('Sign Out')).toBeNull());
  });

  it('seeds the profile avatar with initials only, never the full name or email (review fix — PII leak to a third-party CDN)', () => {
    render(<TopUtilityBar />);

    const avatar = screen.getByAltText('Profile') as HTMLImageElement;
    expect(avatar.src).toContain('name=JO');
    expect(avatar.src).not.toContain(encodeURIComponent('J. Robert Oppenheimer'));
    expect(avatar.src).not.toContain(encodeURIComponent('robert@example.com'));
  });
});
