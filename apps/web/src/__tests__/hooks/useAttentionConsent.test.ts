import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const { useAuthMock, createClientMock, setAttentionConsentMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  createClientMock: vi.fn(),
  setAttentionConsentMock: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));
vi.mock('@/lib/supabase/client', () => ({ createClient: createClientMock }));
vi.mock('@/services/users.service', () => ({
  usersService: { setAttentionConsent: setAttentionConsentMock },
}));

import { useAttentionConsent } from '@/hooks/useAttentionConsent';

const USER_ID = 'user_abc123';

function mockSupabaseUsersRead(result: { data: { attention_consent: boolean | null } | null; error: unknown }) {
  createClientMock.mockReturnValue({
    from: vi.fn(() => ({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          maybeSingle: vi.fn(async () => result),
        })),
      })),
    })),
  });
}

beforeEach(() => {
  useAuthMock.mockReset();
  createClientMock.mockReset();
  setAttentionConsentMock.mockReset();
  useAuthMock.mockReturnValue({ user: { id: USER_ID, email: 'a@b.com' } });
  localStorage.clear();
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

  it('degrades to NOT showing the modal on a Supabase read error, rather than crashing or nagging on broken data (AC-9)', async () => {
    mockSupabaseUsersRead({ data: null, error: { message: 'db unreachable' } });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(false);
  });

  it('degrades to NOT showing the modal when the read call itself throws', async () => {
    createClientMock.mockReturnValue({
      from: vi.fn(() => ({
        select: vi.fn(() => ({
          eq: vi.fn(() => ({
            maybeSingle: vi.fn(async () => {
              throw new Error('network down');
            }),
          })),
        })),
      })),
    });

    const { result } = renderHook(() => useAttentionConsent());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.showModal).toBe(false);
  });

  it('does not query at all before there is an authenticated user', () => {
    useAuthMock.mockReturnValue({ user: null });

    renderHook(() => useAttentionConsent());

    expect(createClientMock).not.toHaveBeenCalled();
  });

  it('accept() calls usersService.setAttentionConsent(true), sets consentStatus, and dismisses the modal', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });
    setAttentionConsentMock.mockResolvedValue(undefined);

    const { result } = renderHook(() => useAttentionConsent());
    await waitFor(() => expect(result.current.showModal).toBe(true));

    await act(async () => {
      await result.current.accept();
    });

    expect(setAttentionConsentMock).toHaveBeenCalledWith(true);
    expect(result.current.consentStatus).toBe('accepted');
    expect(result.current.showModal).toBe(false);
    expect(localStorage.getItem(`hie:attention-consent-dismissed:${USER_ID}`)).toBe('1');
  });

  it('decline() makes NO API call, sets consentStatus to declined, and dismisses the modal', async () => {
    mockSupabaseUsersRead({ data: { attention_consent: null }, error: null });

    const { result } = renderHook(() => useAttentionConsent());
    await waitFor(() => expect(result.current.showModal).toBe(true));

    act(() => {
      result.current.decline();
    });

    expect(setAttentionConsentMock).not.toHaveBeenCalled();
    expect(result.current.consentStatus).toBe('declined');
    expect(result.current.showModal).toBe(false);
    expect(localStorage.getItem(`hie:attention-consent-dismissed:${USER_ID}`)).toBe('1');
  });
});
