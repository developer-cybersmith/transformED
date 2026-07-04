import { useEffect } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';

const { mockGetUser, mockSignOut, mockOnAuthStateChange, mockUnsubscribe, mockCreateClient } = vi.hoisted(() => ({
  mockGetUser: vi.fn(),
  mockSignOut: vi.fn(),
  mockOnAuthStateChange: vi.fn(),
  mockUnsubscribe: vi.fn(),
  mockCreateClient: vi.fn(),
}));

let authChangeCallback: ((event: string, session: unknown) => void) | undefined;

vi.mock('@/lib/supabase/client', () => ({
  createClient: mockCreateClient,
}));

beforeEach(() => {
  mockCreateClient.mockReset();
  mockCreateClient.mockImplementation(() => ({
    auth: {
      getUser: mockGetUser,
      signOut: mockSignOut,
      onAuthStateChange: (cb: (event: string, session: unknown) => void) => {
        authChangeCallback = cb;
        return { data: { subscription: { unsubscribe: mockUnsubscribe } } };
      },
    },
  }));
});

function Probe() {
  const { user, isLoading, error } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="user">{user ? user.email : 'none'}</span>
      <span data-testid="error">{error ?? 'none'}</span>
    </div>
  );
}

function LogoutProbe({ captureRef }: { captureRef: { current: (() => Promise<void>) | undefined } }) {
  const { logout } = useAuth();
  useEffect(() => {
    captureRef.current = logout;
  }, [logout, captureRef]);
  return null;
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
}

const SUPABASE_USER = {
  id: 'user_1',
  email: 'student@example.com',
  user_metadata: { full_name: 'Student One' },
};

beforeEach(() => {
  mockGetUser.mockReset();
  mockSignOut.mockReset();
  mockOnAuthStateChange.mockReset();
  mockUnsubscribe.mockReset();
  authChangeCallback = undefined;
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, href: '' },
  });
});

describe('AuthContext — initial session', () => {
  it('sets the user on a successful getUser() call', async () => {
    mockGetUser.mockResolvedValue({ data: { user: SUPABASE_USER }, error: null });

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('student@example.com'));
    expect(screen.getByTestId('loading').textContent).toBe('false');
    expect(screen.getByTestId('error').textContent).toBe('none');
  });

  it('sets user to null and records an error message when getUser() fails (not just a console.log)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: new Error('session expired') });

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(screen.getByTestId('error').textContent).not.toBe('none');
  });
});

describe('AuthContext — live auth state subscription', () => {
  it('subscribes to onAuthStateChange and updates user on a SIGNED_IN event without a manual refresh', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');

    act(() => {
      authChangeCallback?.('SIGNED_IN', { user: SUPABASE_USER });
    });

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('student@example.com'));
  });

  it('clears the user on a SIGNED_OUT event', async () => {
    mockGetUser.mockResolvedValue({ data: { user: SUPABASE_USER }, error: null });
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('student@example.com'));

    act(() => {
      authChangeCallback?.('SIGNED_OUT', null);
    });

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('none'));
  });

  it('ignores the INITIAL_SESSION event — the mount-time getUser() call is the authoritative source', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    act(() => {
      authChangeCallback?.('INITIAL_SESSION', { user: SUPABASE_USER });
    });

    expect(screen.getByTestId('user').textContent).toBe('none');
  });

  it('unsubscribes from onAuthStateChange on unmount', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    const { unmount } = renderWithProvider();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    unmount();

    expect(mockUnsubscribe).toHaveBeenCalled();
  });

  it('does not let a slow, stale getUser() resolution overwrite a SIGNED_OUT event that arrived first', async () => {
    let resolveGetUser: (value: { data: { user: typeof SUPABASE_USER }; error: null }) => void;
    mockGetUser.mockReturnValue(
      new Promise((resolve) => {
        resolveGetUser = resolve;
      })
    );

    renderWithProvider();

    // A live SIGNED_OUT event arrives while the mount-time getUser() is still in flight.
    act(() => {
      authChangeCallback?.('SIGNED_OUT', null);
    });
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('none'));

    // The stale getUser() call now resolves with a (stale) user — it must NOT win.
    await act(async () => {
      resolveGetUser({ data: { user: SUPABASE_USER }, error: null });
    });

    expect(screen.getByTestId('user').textContent).toBe('none');
  });

  it('calls createClient exactly once across re-renders (lazy ref init, not on every render)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    const { rerender } = renderWithProvider();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    rerender(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    rerender(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    expect(mockCreateClient).toHaveBeenCalledTimes(1);
  });
});

describe('AuthContext — logout', () => {
  it('clears user and redirects to /signin on successful signOut', async () => {
    mockGetUser.mockResolvedValue({ data: { user: SUPABASE_USER }, error: null });
    mockSignOut.mockResolvedValue({ error: null });

    const logoutRef: { current: (() => Promise<void>) | undefined } = { current: undefined };
    render(
      <AuthProvider>
        <LogoutProbe captureRef={logoutRef} />
      </AuthProvider>
    );
    await waitFor(() => expect(logoutRef.current).toBeDefined());

    await act(async () => {
      await logoutRef.current!();
    });

    expect(window.location.href).toBe('/signin');
  });

  it('still clears local state and redirects even when signOut() throws (fail closed, not stuck logged-in)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: SUPABASE_USER }, error: null });
    mockSignOut.mockRejectedValue(new Error('network error'));

    const logoutRef: { current: (() => Promise<void>) | undefined } = { current: undefined };
    render(
      <AuthProvider>
        <LogoutProbe captureRef={logoutRef} />
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(logoutRef.current).toBeDefined());

    await act(async () => {
      await logoutRef.current!();
    });

    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(window.location.href).toBe('/signin');
  });
});
