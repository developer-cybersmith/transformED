import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({
  default: useSWRMock,
}));

const { getDashboardMock, useAuthMock } = vi.hoisted(() => ({
  getDashboardMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock('@/services/dashboard.service', () => ({
  dashboardService: { getDashboard: getDashboardMock },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: useAuthMock,
}));

import { useDashboard } from '@/hooks/useDashboard';

beforeEach(() => {
  useSWRMock.mockReset();
  getDashboardMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: { id: 'user_1', email: 'a@b.com' } });
  useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: true });
});

describe('useDashboard', () => {
  it('retries on error (S2-27 review fix: required for polling to self-heal past a transient failure -- see refreshInterval tests)', () => {
    renderHook(() => useDashboard());

    expect(useSWRMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.any(Function),
      expect.objectContaining({ shouldRetryOnError: true })
    );
  });

  it('scopes the SWR cache key by the current user id — a shared browser tab must not leak one account\'s dashboard into another\'s', () => {
    renderHook(() => useDashboard());

    expect(useSWRMock).toHaveBeenCalledWith('dashboard:user_1', expect.any(Function), expect.anything());
  });

  it('uses a different cache key for a different user', () => {
    useAuthMock.mockReturnValue({ user: { id: 'user_2', email: 'c@d.com' } });

    renderHook(() => useDashboard());

    expect(useSWRMock).toHaveBeenCalledWith('dashboard:user_2', expect.any(Function), expect.anything());
  });

  it('does not fetch at all when there is no authenticated user yet', () => {
    useAuthMock.mockReturnValue({ user: null });

    renderHook(() => useDashboard());

    expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
  });

  it('returns the fetched dashboard data and stops loading', async () => {
    const data = { continueLearning: null, recentLessons: [], learningPulse: undefined };
    useSWRMock.mockReturnValue({ data, error: undefined, isLoading: false });

    const { result } = renderHook(() => useDashboard());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(data);
  });

  it('surfaces a fetch error and returns null data', () => {
    const err = new Error('network error');
    useSWRMock.mockReturnValue({ data: undefined, error: err, isLoading: false });

    const { result } = renderHook(() => useDashboard());

    expect(result.current.error).toBe(err);
    expect(result.current.data).toBeNull();
  });
});

describe('useDashboard — auto-poll while a lesson is still generating (S2-27)', () => {
  function getRefreshInterval(): (data: unknown) => number {
    renderHook(() => useDashboard());
    const options = useSWRMock.mock.calls[0][2];
    return options.refreshInterval;
  }

  it('polls when continueLearning is still processing', () => {
    const refreshInterval = getRefreshInterval();
    const data = { continueLearning: { lesson_id: 'l1', status: 'queued' }, recentLessons: [], learningPulse: undefined };

    expect(refreshInterval(data)).toBeGreaterThan(0);
  });

  it('polls when any recentLessons entry is still processing, even if continueLearning is null', () => {
    const refreshInterval = getRefreshInterval();
    const data = {
      continueLearning: null,
      recentLessons: [{ lesson_id: 'l1', status: 'ready' }, { lesson_id: 'l2', status: 'running' }],
      learningPulse: undefined,
    };

    expect(refreshInterval(data)).toBeGreaterThan(0);
  });

  it('does not poll when everything is in a terminal state', () => {
    const refreshInterval = getRefreshInterval();
    const data = {
      continueLearning: { lesson_id: 'l1', status: 'ready' },
      recentLessons: [{ lesson_id: 'l2', status: 'failed' }],
      learningPulse: undefined,
    };

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
    const data = { continueLearning: { lesson_id: 'l1', status: 'queued' }, recentLessons: [], learningPulse: undefined };

    expect(refreshInterval(data)).toBeGreaterThan(0);

    vi.setSystemTime(20 * 60 * 1000 + 1); // just past the 20-minute cap
    expect(refreshInterval(data)).toBe(0);

    vi.useRealTimers();
  });
});
