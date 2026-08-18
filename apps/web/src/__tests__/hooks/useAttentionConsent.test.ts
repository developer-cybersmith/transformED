import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const { useAuthMock, createClientMock, recordConsentMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  createClientMock: vi.fn(),
  recordConsentMock: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));
vi.mock('@/lib/supabase/client', () => ({ createClient: createClientMock }));
vi.mock('@/lib/assessment', () => ({ recordConsent: recordConsentMock }));

import { useAttentionConsent } from '@/hooks/useAttentionConsent';

const USER_ID = 'user_abc123';

function mockSupabaseUsersRead(usersRead: { data: { attention_consent: boolean | null } | null; error: unknown }) {
  createClientMock.mockReturnValue({
    from: vi.fn(() => ({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          maybeSingle: vi.fn(async () => usersRead),
        })),
      })),
    })),
  });
}

let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  useAuthMock.mockReset();
  createClientMock.mockReset();
  recordConsentMock.mockReset();
  recordConsentMock.mockResolvedValue({
    id: 'consent_1',
    user_id: USER_ID,
    consent_type: 'attention_tracking',
    policy_version: 'v1',
    consented_at: null,
  });
  useAuthMock.mockReturnValue({ user: { id: USER_ID, email: 'a@b.com' } });
  localStorage.clear();
  consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  consoleErrorSpy.mockRestore();
});

describe('useAttentionConsent (S3-01 AC-6)', () => {
  it('shows the modal when Supabase reports attention_consent = null and no dismissal exists', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(true);
    expect(result.current.consentStatus).toBe('unknown');
  });

  it('never shows the modal when attention_consent is already true', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: true }, error: null });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(false);
    expect(result.current.consentStatus).toBe('accepted');
  });

  it('does not re-show the modal when a dismissal key already exists for this user, even with consent still null', async () => {
    localStorage.setItem(`hie:attention-consent-dismissed:${USER_ID}`, '1');
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(false);
  });

  it('shows the modal when Supabase finds no row at all for the user, treating it as "not yet true" rather than a read failure', async () => {
    mockSupabaseUsersRead({ data: null, error: null });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(true);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it('degrades to NOT showing the modal on a Supabase read error, rather than crashing or nagging on broken data (AC-9), and logs it', async () => {
    const dbError = { message: 'db unreachable' };
    mockSupabaseUsersRead({ data: null, error: dbError });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to read consent status'), dbError);
  });

  it('degrades to NOT showing the modal when the read call itself throws, and logs it', async () => {
    const thrown = new Error('network down');
    createClientMock.mockReturnValue({
      from: vi.fn(() => ({
        select: vi.fn(() => ({
          eq: vi.fn(() => ({
            maybeSingle: vi.fn(async () => {
              throw thrown;
            }),
          })),
        })),
      })),
    });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to read consent status'), thrown);
  });

  it('does not query and resolves isLoading to false when there is no authenticated user', () => {
    useAuthMock.mockReturnValue({ user: null });

    const { result } = renderHook(() => useAttentionConsent());

    expect(createClientMock).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.showModal).toBe(false);
  });

  it('does not re-query when the user object is replaced with a new object of the same id (e.g. a token refresh)', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });
    const { result, rerender } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(createClientMock).toHaveBeenCalledTimes(1);

    useAuthMock.mockReturnValue({ user: { id: USER_ID, email: 'a@b.com' } });
    rerender();

    expect(createClientMock).toHaveBeenCalledTimes(1);
  });

  it('accept() calls POST /api/assessment/consent for attention_tracking, sets consentStatus, and dismisses the modal', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });

    const { result } = renderHook(() => useAttentionConsent());
    await waitFor(() => expect(result.current.showModal).toBe(true));

    await act(async () => {
      await result.current.accept();
    });

    expect(recordConsentMock).toHaveBeenCalledWith(
      expect.objectContaining({ consent_type: 'attention_tracking' })
    );
    expect(result.current.consentStatus).toBe('accepted');
    expect(result.current.showModal).toBe(false);
    expect(localStorage.getItem(`hie:attention-consent-dismissed:${USER_ID}`)).toBe('1');
  });

  it('accept() logs and rethrows when the backend call fails, without dismissing the modal', async () => {
    const requestError = { message: 'network error' };
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });
    recordConsentMock.mockRejectedValue(requestError);

    const { result } = renderHook(() => useAttentionConsent());
    await waitFor(() => expect(result.current.showModal).toBe(true));

    await act(async () => {
      await expect(result.current.accept()).rejects.toBeTruthy();
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to record consent'), requestError);
    expect(result.current.consentStatus).toBe('unknown');
    expect(result.current.showModal).toBe(true);
  });

  it('decline() makes NO API call, sets consentStatus to declined, and dismisses the modal', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });

    const { result } = renderHook(() => useAttentionConsent());
    await waitFor(() => expect(result.current.showModal).toBe(true));

    act(() => {
      result.current.decline();
    });

    expect(recordConsentMock).not.toHaveBeenCalled();
    expect(result.current.consentStatus).toBe('declined');
    expect(result.current.showModal).toBe(false);
    expect(localStorage.getItem(`hie:attention-consent-dismissed:${USER_ID}`)).toBe('1');
  });

  it('a decline() that lands while accept() is still in flight is not overwritten once accept() later resolves', async () => {
    let resolveConsent!: (value: { id: string; user_id: string; consent_type: string; policy_version: string; consented_at: string | null }) => void;
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });
    recordConsentMock.mockReturnValue(new Promise((resolve) => { resolveConsent = resolve; }));

    const { result } = renderHook(() => useAttentionConsent());
    await waitFor(() => expect(result.current.showModal).toBe(true));

    let acceptPromise!: Promise<void>;
    act(() => {
      acceptPromise = result.current.accept();
    });

    // Decline lands first, while the accept() request is still pending.
    act(() => {
      result.current.decline();
    });
    expect(result.current.consentStatus).toBe('declined');

    // The stale accept() now resolves -- it must not flip the final state
    // back to "accepted".
    await act(async () => {
      resolveConsent({ id: 'consent_1', user_id: USER_ID, consent_type: 'attention_tracking', policy_version: 'v1', consented_at: null });
      await acceptPromise;
    });

    expect(recordConsentMock).toHaveBeenCalledTimes(1);
    expect(result.current.consentStatus).toBe('declined');
  });
});
