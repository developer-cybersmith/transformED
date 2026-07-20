import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({
  default: useSWRMock,
}));

const { getSessionReportMock } = vi.hoisted(() => ({
  getSessionReportMock: vi.fn(),
}));

vi.mock('@/lib/assessment', () => ({
  getSessionReport: getSessionReportMock,
}));

import { useSessionReport } from '@/hooks/useSessionReport';

beforeEach(() => {
  useSWRMock.mockReset();
  getSessionReportMock.mockReset();
  useSWRMock.mockReturnValue({ data: null, error: undefined, isLoading: true });
});

describe('useSessionReport', () => {
  it('does not fetch when sessionId is empty', () => {
    renderHook(() => useSessionReport(''));

    expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
  });

  it('keys the SWR cache by sessionId', () => {
    renderHook(() => useSessionReport('sess_1'));

    expect(useSWRMock).toHaveBeenCalledWith(
      'session-report:sess_1',
      expect.any(Function),
      expect.anything()
    );
  });

  it('does not retry indefinitely on error — a permanently 404ing session must not hammer the backend', () => {
    renderHook(() => useSessionReport('sess_1'));

    expect(useSWRMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.any(Function),
      expect.objectContaining({ shouldRetryOnError: false })
    );
  });

  it('returns the fetched report and stops loading', async () => {
    useSWRMock.mockReturnValue({ data: { session_id: 'sess_1' }, error: undefined, isLoading: false });

    const { result } = renderHook(() => useSessionReport('sess_1'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.report).toEqual({ session_id: 'sess_1' });
  });

  it('surfaces a fetch error', () => {
    const err = new Error('network error');
    useSWRMock.mockReturnValue({ data: undefined, error: err, isLoading: false });

    const { result } = renderHook(() => useSessionReport('sess_1'));

    expect(result.current.error).toBe(err);
    expect(result.current.report).toBeNull();
  });
});
