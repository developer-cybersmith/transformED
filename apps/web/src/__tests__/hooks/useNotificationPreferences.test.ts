import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const { useAuthMock, createClientMock, updateNotificationsMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  createClientMock: vi.fn(),
  updateNotificationsMock: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));
vi.mock('@/lib/supabase/client', () => ({ createClient: createClientMock }));
vi.mock('@/services/settings.service', () => ({
  settingsService: { updateNotifications: updateNotificationsMock },
}));

import { useNotificationPreferences } from '@/hooks/useNotificationPreferences';

const USER_ID = 'user_abc123';

const ALL_TRUE = {
  session_report_email: true,
  lesson_ready_email: true,
  weekly_progress_email: true,
  streak_reminders: true,
};

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

  it('updatePreference optimistically flips the field and calls the real service with only that field (AC-3, AC-6, AC-7)', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });
    updateNotificationsMock.mockResolvedValue({
      user_id: USER_ID,
      ...ALL_TRUE,
      streak_reminders: false,
      updated_at: '2026-08-06T12:00:00Z',
    });

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.updatePreference('streak_reminders', false);
    });

    expect(updateNotificationsMock).toHaveBeenCalledWith({ streak_reminders: false });
    expect(updateNotificationsMock).toHaveBeenCalledTimes(1);
    expect(result.current.preferences.streak_reminders).toBe(false);
    // AC-6: never sends user_id; AC-7: never an empty/multi-field body.
    const [sentBody] = updateNotificationsMock.mock.calls[0];
    expect(Object.keys(sentBody)).toEqual(['streak_reminders']);
  });

  it('rolls back to the prior value and logs when the update fails (AC-4)', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });
    const failure = new Error('network error');
    updateNotificationsMock.mockRejectedValue(failure);

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.updatePreference('streak_reminders', false);
    });

    expect(result.current.preferences.streak_reminders).toBe(true);
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('failed to update'), failure);
  });

  it('a stale failed request cannot roll back over a newer request for the same field (AC-5 race guard)', async () => {
    mockSupabaseRead({ data: ALL_TRUE, error: null });

    let rejectFirst!: (err: unknown) => void;
    updateNotificationsMock
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject; }))
      .mockResolvedValueOnce({ user_id: USER_ID, ...ALL_TRUE, streak_reminders: true, updated_at: 't2' })
      .mockResolvedValueOnce({ user_id: USER_ID, ...ALL_TRUE, streak_reminders: false, updated_at: 't3' });

    const { result } = renderHook(() => useNotificationPreferences());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Click 1: false (stays pending). Click 2: true. Click 3: false (the real final intent).
    let firstUpdate!: Promise<void>;
    act(() => {
      firstUpdate = result.current.updatePreference('streak_reminders', false);
    });
    await act(async () => {
      await result.current.updatePreference('streak_reminders', true);
    });
    await act(async () => {
      await result.current.updatePreference('streak_reminders', false);
    });
    expect(result.current.preferences.streak_reminders).toBe(false);

    // The stale first request now fails -- its rollback target (the value before
    // click 1, i.e. true) must NOT overwrite click 3's more recent false.
    await act(async () => {
      rejectFirst(new Error('stale network error'));
      await firstUpdate;
    });

    expect(result.current.preferences.streak_reminders).toBe(false);
  });

  it('does not query before there is an authenticated user', () => {
    useAuthMock.mockReturnValue({ user: null });

    const { result } = renderHook(() => useNotificationPreferences());

    expect(createClientMock).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.preferences).toEqual(ALL_TRUE);
  });
});
