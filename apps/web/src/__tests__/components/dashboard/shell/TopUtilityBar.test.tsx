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

describe('TopUtilityBar — mobile nav (Sidebar is hidden lg:flex with no other mobile entry point)', () => {
  it('opens on click, showing every Sidebar nav destination plus Settings and Sign Out', async () => {
    const user = userEvent.setup();
    render(<TopUtilityBar />);

    await user.click(screen.getByRole('button', { name: /toggle navigation menu/i }));

    expect(screen.getByRole('link', { name: /dashboard/i })).not.toBeNull();
    // Story 2-47 (S4-06): "My Library" removed, folded into "My Books".
    expect(screen.getByRole('link', { name: /my books/i })).not.toBeNull();
    expect(screen.getByRole('link', { name: /upload pdf/i })).not.toBeNull();
    expect(screen.getByRole('link', { name: /reports/i })).not.toBeNull();
    expect(screen.getByRole('link', { name: /settings/i })).not.toBeNull();
    expect(screen.getByText('Sign Out')).not.toBeNull();
  });

  it('closes on Escape', async () => {
    const user = userEvent.setup();
    render(<TopUtilityBar />);

    await user.click(screen.getByRole('button', { name: /toggle navigation menu/i }));
    expect(screen.getByRole('link', { name: /dashboard/i })).not.toBeNull();

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('link', { name: /dashboard/i })).toBeNull());
  });

  it('closes after a nav link is clicked', async () => {
    const user = userEvent.setup();
    render(<TopUtilityBar />);

    await user.click(screen.getByRole('button', { name: /toggle navigation menu/i }));
    await user.click(screen.getByRole('link', { name: /my books/i }));

    await waitFor(() => expect(screen.queryByRole('link', { name: /my books/i })).toBeNull());
  });

  it('calls logout and closes when Sign Out is clicked', async () => {
    const user = userEvent.setup();
    render(<TopUtilityBar />);

    await user.click(screen.getByRole('button', { name: /toggle navigation menu/i }));
    await user.click(screen.getByText('Sign Out'));

    expect(logoutMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText('Sign Out')).toBeNull());
  });
});
