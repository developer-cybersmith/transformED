import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({
  default: useSWRMock,
}));

const { getDashboardMock } = vi.hoisted(() => ({
  getDashboardMock: vi.fn(),
}));

vi.mock('@/services/dashboard.service', () => ({
  dashboardService: { getDashboard: getDashboardMock },
}));

import { useDashboard } from '@/hooks/useDashboard';

beforeEach(() => {
  useSWRMock.mockReset();
  getDashboardMock.mockReset();
  useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: true });
});

describe('useDashboard', () => {
  it('does not retry indefinitely on error', () => {
    renderHook(() => useDashboard());

    expect(useSWRMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.any(Function),
      expect.objectContaining({ shouldRetryOnError: false })
    );
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
