import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({
  default: useSWRMock,
}));

const { getLibraryMock, useAuthMock } = vi.hoisted(() => ({
  getLibraryMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock('@/services/library.service', () => ({
  libraryService: { getLibrary: getLibraryMock },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: useAuthMock,
}));

import { useLibrary } from '@/hooks/useLibrary';

beforeEach(() => {
  useSWRMock.mockReset();
  getLibraryMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: { id: 'user_1', email: 'a@b.com' } });
  useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: true });
});

describe('useLibrary', () => {
  it('retries on error (S2-27 review fix: required for polling to self-heal past a transient failure -- see refreshInterval tests)', () => {
    renderHook(() => useLibrary());

    expect(useSWRMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.any(Function),
      expect.objectContaining({ shouldRetryOnError: true })
    );
  });

  it('scopes the SWR cache key by the current user id — a shared browser tab must not leak one account\'s library into another\'s', () => {
    renderHook(() => useLibrary());

    expect(useSWRMock).toHaveBeenCalledWith('library:user_1', expect.any(Function), expect.anything());
  });

  it('uses a different cache key for a different user', () => {
    useAuthMock.mockReturnValue({ user: { id: 'user_2', email: 'c@d.com' } });

    renderHook(() => useLibrary());

    expect(useSWRMock).toHaveBeenCalledWith('library:user_2', expect.any(Function), expect.anything());
  });

  it('does not fetch at all when there is no authenticated user yet', () => {
    useAuthMock.mockReturnValue({ user: null });

    renderHook(() => useLibrary());

    expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
  });

  it('returns the fetched library data and stops loading', async () => {
    const data = { all: [], ready: [], processing: [], failed: [] };
    useSWRMock.mockReturnValue({ data, error: undefined, isLoading: false });

    const { result } = renderHook(() => useLibrary());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(data);
  });

  it('surfaces a fetch error and returns null data', () => {
    const err = new Error('network error');
    useSWRMock.mockReturnValue({ data: undefined, error: err, isLoading: false });

    const { result } = renderHook(() => useLibrary());

    expect(result.current.error).toBe(err);
    expect(result.current.data).toBeNull();
  });
});

describe('useLibrary — auto-poll while a lesson is still generating (S2-27)', () => {
  function getRefreshInterval(): (data: unknown) => number {
    renderHook(() => useLibrary());
    const options = useSWRMock.mock.calls[0][2];
    return options.refreshInterval;
  }

  it('polls when there is at least one processing lesson', () => {
    const refreshInterval = getRefreshInterval();
    const data = { all: [], ready: [], processing: [{ lesson_id: 'l1', status: 'running' }], failed: [] };

    expect(refreshInterval(data)).toBeGreaterThan(0);
  });

  it('does not poll when nothing is processing', () => {
    const refreshInterval = getRefreshInterval();
    const data = { all: [], ready: [], processing: [], failed: [] };

    expect(refreshInterval(data)).toBe(0);
  });

  it('does not poll before any data has been fetched yet', () => {
    const refreshInterval = getRefreshInterval();

    expect(refreshInterval(undefined)).toBe(0);
  });

  it('stops polling after MAX_POLL_DURATION_MS even if still processing (review fix — a genuinely-stuck backend job must not poll forever)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const refreshInterval = getRefreshInterval();
    const data = { all: [], ready: [], processing: [{ lesson_id: 'l1', status: 'running' }], failed: [] };

    expect(refreshInterval(data)).toBeGreaterThan(0);

    vi.setSystemTime(20 * 60 * 1000 + 1); // just past the 20-minute cap
    expect(refreshInterval(data)).toBe(0);

    vi.useRealTimers();
  });

  it('a later lesson starts its own fresh polling window instead of inheriting an already-expired one', () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const refreshInterval = getRefreshInterval();
    const processing = { all: [], ready: [], processing: [{ lesson_id: 'l1', status: 'running' }], failed: [] };
    const idle = { all: [], ready: [], processing: [], failed: [] };

    refreshInterval(processing);
    vi.setSystemTime(20 * 60 * 1000 + 1);
    expect(refreshInterval(processing)).toBe(0); // expired

    refreshInterval(idle); // nothing processing -- resets the window
    vi.setSystemTime(20 * 60 * 1000 + 2);
    expect(refreshInterval(processing)).toBeGreaterThan(0); // fresh window

    vi.useRealTimers();
  });
});
