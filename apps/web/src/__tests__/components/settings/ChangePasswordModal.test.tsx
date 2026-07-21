import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChangePasswordModal } from '@/components/settings/ChangePasswordModal';

const { signInWithPasswordMock, updateUserMock } = vi.hoisted(() => ({
  signInWithPasswordMock: vi.fn(),
  updateUserMock: vi.fn(),
}));

vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    auth: {
      signInWithPassword: signInWithPasswordMock,
      updateUser: updateUserMock,
    },
  }),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'usr_1', email: 'robert@example.com' } }),
}));

function getInputs() {
  const [current, next, confirm] = screen.getAllByDisplayValue('') as HTMLInputElement[];
  return { current, next, confirm };
}

beforeEach(() => {
  signInWithPasswordMock.mockReset();
  updateUserMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ChangePasswordModal', () => {
  it('rejects submission when the new password is the same as the current password, without calling Supabase', async () => {
    const user = userEvent.setup();
    render(<ChangePasswordModal isOpen={true} onClose={vi.fn()} />);

    const { current, next, confirm } = getInputs();
    await user.type(current, 'samepassword1');
    await user.type(next, 'samepassword1');
    await user.type(confirm, 'samepassword1');
    await user.click(screen.getByText('Update Password'));

    expect(screen.getByText('New password must be different from your current password.')).not.toBeNull();
    expect(signInWithPasswordMock).not.toHaveBeenCalled();
  });

  it('does not fire a second signInWithPassword call on a rapid double-submit (reentrancy guard)', async () => {
    const user = userEvent.setup();
    signInWithPasswordMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ error: null }), 50))
    );
    updateUserMock.mockResolvedValue({ error: null });

    render(<ChangePasswordModal isOpen={true} onClose={vi.fn()} />);
    const { current, next, confirm } = getInputs();
    await user.type(current, 'oldpassword1');
    await user.type(next, 'newpassword1');
    await user.type(confirm, 'newpassword1');

    const submitButton = screen.getByText('Update Password').closest('button')!;
    await user.click(submitButton);
    await user.click(submitButton); // second click while the first is still in flight

    await waitFor(() => expect(updateUserMock).toHaveBeenCalled());
    expect(signInWithPasswordMock).toHaveBeenCalledTimes(1);
  });

  it('maps a 429 re-auth error to a rate-limit message, not "incorrect password"', async () => {
    const user = userEvent.setup();
    signInWithPasswordMock.mockResolvedValue({ error: { status: 429, message: 'rate limited' } });

    render(<ChangePasswordModal isOpen={true} onClose={vi.fn()} />);
    const { current, next, confirm } = getInputs();
    await user.type(current, 'oldpassword1');
    await user.type(next, 'newpassword1');
    await user.type(confirm, 'newpassword1');
    await user.click(screen.getByText('Update Password'));

    await screen.findByText(/too many attempts/i);
    expect(screen.queryByText('Current password is incorrect.')).toBeNull();
  });

  it('maps a 5xx re-auth error to a generic server-error message, not "incorrect password"', async () => {
    const user = userEvent.setup();
    signInWithPasswordMock.mockResolvedValue({ error: { status: 500, message: 'server error' } });

    render(<ChangePasswordModal isOpen={true} onClose={vi.fn()} />);
    const { current, next, confirm } = getInputs();
    await user.type(current, 'oldpassword1');
    await user.type(next, 'newpassword1');
    await user.type(confirm, 'newpassword1');
    await user.click(screen.getByText('Update Password'));

    await screen.findByText(/something went wrong on our end/i);
    expect(screen.queryByText('Current password is incorrect.')).toBeNull();
  });

  it('still shows "Current password is incorrect" for an actual wrong-password (400) error', async () => {
    const user = userEvent.setup();
    signInWithPasswordMock.mockResolvedValue({ error: { status: 400, message: 'Invalid login credentials' } });

    render(<ChangePasswordModal isOpen={true} onClose={vi.fn()} />);
    const { current, next, confirm } = getInputs();
    await user.type(current, 'wrongpassword');
    await user.type(next, 'newpassword1');
    await user.type(confirm, 'newpassword1');
    await user.click(screen.getByText('Update Password'));

    await screen.findByText('Current password is incorrect.');
  });

  it('sets autoComplete hints on all 3 password fields', () => {
    render(<ChangePasswordModal isOpen={true} onClose={vi.fn()} />);
    const { current, next, confirm } = getInputs();

    expect(current.autocomplete).toBe('current-password');
    expect(next.autocomplete).toBe('new-password');
    expect(confirm.autocomplete).toBe('new-password');
  });

  it('a stale post-success auto-close timer does not force-close a reopened modal (review fix)', async () => {
    vi.useFakeTimers();
    signInWithPasswordMock.mockResolvedValue({ error: null });
    updateUserMock.mockResolvedValue({ error: null });
    const onClose = vi.fn();

    const { rerender } = render(<ChangePasswordModal isOpen={true} onClose={onClose} />);
    const { current, next, confirm } = getInputs();
    fireEvent.change(current, { target: { value: 'oldpassword1' } });
    fireEvent.change(next, { target: { value: 'newpassword1' } });
    fireEvent.change(confirm, { target: { value: 'newpassword1' } });
    fireEvent.click(screen.getByText('Update Password'));

    // Flush the mocked signInWithPassword/updateUser promise chain (real
    // microtasks) without letting real setTimeout time advance.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByText('Password updated successfully.')).not.toBeNull();

    // User manually closes right away (the "X" button, which calls handleClose
    // internally) — well before the 1500ms auto-close timer would fire.
    onClose.mockClear();
    fireEvent.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalledTimes(1);

    // Parent re-opens the modal for a fresh attempt, simulating the user coming
    // right back into the flow within that same window.
    onClose.mockClear();
    rerender(<ChangePasswordModal isOpen={true} onClose={onClose} />);

    act(() => {
      vi.advanceTimersByTime(1500);
    });

    // Without the fix, the untracked original timer would still fire handleClose()
    // here, force-closing the freshly-reopened modal a second time.
    expect(onClose).not.toHaveBeenCalled();
  });
});
