import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Sidebar, mainNavItems } from '@/components/dashboard/shell/Sidebar';

const { logoutMock } = vi.hoisted(() => ({ logoutMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: logoutMock }),
}));

beforeEach(() => {
  logoutMock.mockReset();
  localStorage.clear();
});

describe('Sidebar — main navigation', () => {
  it('exposes a /books entry (W2 AC9) alongside the existing destinations', () => {
    // Story 2-47 (S4-06): /library removed, folded into /books.
    expect(mainNavItems.map((item) => item.href)).toEqual([
      '/dashboard',
      '/books',
      '/upload',
      '/reports',
    ]);
  });

  it('renders the Books link so the book library is reachable from every dashboard route', () => {
    render(<Sidebar />);

    const link = screen.getByRole('link', { name: 'My Books' });
    expect(link.getAttribute('href')).toBe('/books');
  });
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

describe('Sidebar — collapse toggle', () => {
  it('starts expanded by default, with labels visible', () => {
    render(<Sidebar />);

    expect(screen.getByText('My Books')).not.toBeNull();
    expect(screen.getByRole('button', { name: /collapse sidebar/i })).not.toBeNull();
  });

  it('hides nav labels and flips the toggle button after a click', async () => {
    const user = userEvent.setup();
    render(<Sidebar />);

    await user.click(screen.getByRole('button', { name: /collapse sidebar/i }));

    expect(screen.queryByText('My Books')).toBeNull();
    expect(screen.getByRole('button', { name: /expand sidebar/i })).not.toBeNull();
    // The link itself must still be reachable by its accessible (tooltip) name.
    expect(screen.getByRole('link', { name: 'My Books' })).not.toBeNull();
  });

  it('expands again on a second click', async () => {
    const user = userEvent.setup();
    render(<Sidebar />);

    const toggle = () => screen.getByRole('button', { name: /(collapse|expand) sidebar/i });
    await user.click(toggle());
    expect(screen.queryByText('My Books')).toBeNull();

    await user.click(toggle());
    expect(screen.getByText('My Books')).not.toBeNull();
  });

  it('persists the collapsed choice to localStorage and restores it on the next mount', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Sidebar />);

    await user.click(screen.getByRole('button', { name: /collapse sidebar/i }));
    expect(localStorage.getItem('hie:sidebar-collapsed')).toBe('1');
    unmount();

    // A fresh mount (e.g. navigating to a different top-level route, which
    // remounts a brand-new <Sidebar /> per layout.tsx) must come back
    // collapsed, not silently re-expand.
    render(<Sidebar />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /expand sidebar/i })).not.toBeNull(),
    );
    expect(screen.queryByText('My Books')).toBeNull();
  });

  it('does not collide with the Account button\'s accessible name', () => {
    render(<Sidebar />);

    // A loose /account/i match must find exactly the Account button, not
    // also match the toggle's "Collapse/Expand sidebar" label.
    expect(screen.getAllByRole('button', { name: /account/i })).toHaveLength(1);
  });
});
