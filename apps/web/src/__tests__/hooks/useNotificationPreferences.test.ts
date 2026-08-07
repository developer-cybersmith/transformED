import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const { useAuthMock, createClientMock, updateNotificationsMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  createClientMock: vi.fn(),
  updateNotificationsMock: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));
vi.mock('@/lib/supabase/client', () => ({ createClient: createClientMock }));
vi.mock('@/services/settings.service', async () => {
  const actual = await vi.importActual<typeof import('@/services/settings.service')>('@/services/settings.service');
  return {
    ...actual,
    settingsService: { updateNotifications: updateNotificationsMock },
  };
});

import { useNotificationPreferences } from '@/hooks/useNotificationPreferences';

const USER_ID = 'user_abc123';

const ALL_TRUE = {
  session_report_email: true,
  lesson_ready_email: true,
  weekly_progress_email: true,
  streak_reminders: true,
};

function record(overrides: Partial<typeof ALL_TRUE> = {}) {
  return { user_id: USER_ID, ...ALL_TRUE, ...overrides, updated_at: '2026-08-06T12:00:00Z' };
}

function mockSupabaseRead(result: { data: Record<string, boolean> | null; error: unknown }) {
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

let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  useAuthMock.mockReset();
  createClientMock.mockReset();
  updateNotificationsMock.mockReset();
  useAuthMock.mockReturnValue({ user: { id: USER_ID, email: 'a@b.com' } });
  consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  consoleErrorSpy.mockRestore();
});

describe('useNotificationPreferences (S3-07 AC-2)', () => {
  it('reflects the real row values when one exists', async () => {
    mockSupabaseRead({
      data: { session_report_email: false, lesson_ready_email: true, weekly_progress_email: false, streak_reminders: true },
      error: null,
    });

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.preferences).toEqual({
      session_report_email: false,
      lesson_ready_email: true,
      weekly_progress_email: false,
      streak_reminders: true,
    });
  });

  it('defaults all four to true when no row exists yet, without logging', async () => {
    mockSupabaseRead({ data: null, error: null });

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.preferences).toEqual(ALL_TRUE);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it('degrades to all-true defaults AND logs when the read errors', async () => {
    const dbError = { message: 'db down' };
    mockSupabaseRead({ data: null, error: dbError });

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.preferences).toEqual(ALL_TRUE);
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to read'), dbError);
  });

  it('degrades to all-true defaults AND logs when the read throws', async () => {
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

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.preferences).toEqual(ALL_TRUE);
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to read'), thrown);
  });

  it('updatePreference optimistically flips the field, then reconciles with the real service response (AC-3, AC-6, AC-7)', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });
    updateNotificationsMock.mockResolvedValue(record({ streak_reminders: false }));

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.updatePreference('streak_reminders', false);
    });

    // Optimistic: flips synchronously, before the network call settles.
    expect(result.current.preferences.streak_reminders).toBe(false);

    await waitFor(() => expect(updateNotificationsMock).toHaveBeenCalledTimes(1));
    const [sentBody] = updateNotificationsMock.mock.calls[0];
    // AC-6: never sends user_id; AC-7: never an empty/multi-field body.
    expect(Object.keys(sentBody)).toEqual(['streak_reminders']);
    expect(sentBody).toEqual({ streak_reminders: false });

    // Reconciled with the server's returned value, not just the optimistic guess.
    await waitFor(() => expect(result.current.preferences.streak_reminders).toBe(false));
  });

  it('rolls back to the prior value and logs when the update fails, with nothing else pending (AC-4)', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });
    const failure = new Error('network error');
    updateNotificationsMock.mockRejectedValue(failure);

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.updatePreference('streak_reminders', false);
    });

    await waitFor(() => expect(result.current.preferences.streak_reminders).toBe(true));
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to update'), failure);
  });

  it('never sends two overlapping requests for the same field, and the last value clicked is the last request sent (AC-5 race guard)', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });

    let resolveFirst!: (v: ReturnType<typeof record>) => void;
    const firstCallInFlight = new Promise<ReturnType<typeof record>>((resolve) => {
      resolveFirst = resolve;
    });
    updateNotificationsMock
      .mockImplementationOnce(() => firstCallInFlight)
      .mockResolvedValueOnce(record({ streak_reminders: false }));

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Three rapid clicks on the same field before the first request settles.
    act(() => {
      result.current.updatePreference('streak_reminders', false); // click 1 -- fires immediately
      result.current.updatePreference('streak_reminders', true); // click 2 -- queued
      result.current.updatePreference('streak_reminders', false); // click 3 -- overwrites the queue
    });

    // Optimistic UI already reflects the final click.
    expect(result.current.preferences.streak_reminders).toBe(false);
    // Only ONE network call so far -- clicks 2 and 3 were coalesced into the queue,
    // never sent as separate overlapping requests.
    expect(updateNotificationsMock).toHaveBeenCalledTimes(1);
    expect(updateNotificationsMock).toHaveBeenCalledWith({ streak_reminders: false });

    // The first (click 1's) request now resolves.
    await act(async () => {
      resolveFirst(record({ streak_reminders: false }));
      await firstCallInFlight;
    });

    // Only now does the queued final value (click 3's, same as click 1's here)
    // get sent, as the second and only other request for this field.
    await waitFor(() => expect(updateNotificationsMock).toHaveBeenCalledTimes(2));
    expect(updateNotificationsMock).toHaveBeenNthCalledWith(2, { streak_reminders: false });
    await waitFor(() => expect(result.current.preferences.streak_reminders).toBe(false));
  });

  it('does not roll back a failed request if a newer value is already queued behind it', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });

    let rejectFirst!: (err: unknown) => void;
    const firstCallInFlight = new Promise<never>((_resolve, reject) => {
      rejectFirst = reject;
    });
    updateNotificationsMock
      .mockImplementationOnce(() => firstCallInFlight)
      .mockResolvedValueOnce(record({ streak_reminders: true }));

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.updatePreference('streak_reminders', false); // fires, will fail
      result.current.updatePreference('streak_reminders', true); // queued -- the real final intent
    });

    act(() => {
      rejectFirst(new Error('network error'));
    });

    // The failure must NOT roll back over the queued newer value, and the
    // queued value is then sent as its own (second) request.
    await waitFor(() => expect(updateNotificationsMock).toHaveBeenCalledTimes(2));
    expect(result.current.preferences.streak_reminders).toBe(true);
  });

  it('a stale in-flight request from a previous user cannot overwrite the newly-loaded user after a switch', async () => {
    const OTHER_USER_ID = 'user_other456';
    mockSupabaseRead({ data: ALL_TRUE, error: null });

    let resolveStale!: (v: ReturnType<typeof record>) => void;
    const staleRequest = new Promise<ReturnType<typeof record>>((resolve) => {
      resolveStale = resolve;
    });
    updateNotificationsMock.mockImplementationOnce(() => staleRequest);

    const { result, rerender } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.updatePreference('streak_reminders', false); // user A's request, left unresolved
    });
    expect(updateNotificationsMock).toHaveBeenCalledTimes(1);

    // User switches (e.g. sign out -> sign in as someone else, same mounted tree).
    useAuthMock.mockReturnValue({ user: { id: OTHER_USER_ID, email: 'b@c.com' } });
    mockSupabaseRead({ data: { ...ALL_TRUE, streak_reminders: true }, error: null });
    rerender();
    await waitFor(() => expect(result.current.preferences.streak_reminders).toBe(true));

    // User A's stale request now resolves -- must not touch user B's state.
    await act(async () => {
      resolveStale(record({ streak_reminders: false }));
      await staleRequest;
    });

    expect(result.current.preferences.streak_reminders).toBe(true);
  });

  it('does not query before there is an authenticated user', () => {
    useAuthMock.mockReturnValue({ user: null });

    const { result } = renderHook(() => useNotificationPreferences());

    expect(createClientMock).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.preferences).toEqual(ALL_TRUE);
  });

  it('updatePreference is a no-op when called before there is an authenticated user', () => {
    useAuthMock.mockReturnValue({ user: null });
    const { result } = renderHook(() => useNotificationPreferences());

    act(() => {
      result.current.updatePreference('streak_reminders', false);
    });

    expect(updateNotificationsMock).not.toHaveBeenCalled();
    expect(result.current.preferences).toEqual(ALL_TRUE);
  });
});
