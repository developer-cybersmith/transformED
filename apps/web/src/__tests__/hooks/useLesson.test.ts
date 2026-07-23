import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({
  default: useSWRMock,
}));

const { getLessonPackageMock } = vi.hoisted(() => ({
  getLessonPackageMock: vi.fn(),
}));

vi.mock('@/services/lesson.service', () => ({
  lessonService: { getLessonPackage: getLessonPackageMock },
}));

import { useLesson } from '@/hooks/useLesson';

beforeEach(() => {
  useSWRMock.mockReset();
  getLessonPackageMock.mockReset();
  useSWRMock.mockReturnValue({ data: null, error: undefined, isLoading: true });
});

describe('useLesson', () => {
  it('disables revalidateOnFocus — a focus-triggered refetch would silently reset mid-lesson player state on an unchanged lesson', () => {
    renderHook(() => useLesson('lsn_1'));

    expect(useSWRMock).toHaveBeenCalledWith(
      'lesson:lsn_1',
      expect.any(Function),
      expect.objectContaining({ revalidateOnFocus: false })
    );
  });

  it('does not fetch when lessonId is empty', () => {
    renderHook(() => useLesson(''));

    expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
  });

  it('returns the resolved content as lesson, and stops loading, for a ready response (S1-7)', async () => {
    useSWRMock.mockReturnValue({
      data: { lesson_id: 'lsn_1', status: 'ready', title: 't', error: null, created_at: null, completed_at: null, content: { lesson_id: 'lsn_1' } },
      error: undefined,
      isLoading: false,
    });

    const { result } = renderHook(() => useLesson('lsn_1'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.lesson).toEqual({ lesson_id: 'lsn_1' });
    expect(result.current.status).toBe('ready');
    expect(result.current.serverError).toBeNull();
  });

  it('surfaces status and a null lesson for a still-running response, without treating it as an error (S1-7)', async () => {
    useSWRMock.mockReturnValue({
      data: { lesson_id: 'lsn_1', status: 'running', title: null, error: null, created_at: null, completed_at: null, content: null },
      error: undefined,
      isLoading: false,
    });

    const { result } = renderHook(() => useLesson('lsn_1'));

    expect(result.current.lesson).toBeNull();
    expect(result.current.status).toBe('running');
    expect(result.current.error).toBeUndefined();
  });

  it('surfaces the real backend error message for a failed response (S1-7)', async () => {
    useSWRMock.mockReturnValue({
      data: { lesson_id: 'lsn_1', status: 'failed', title: null, error: 'Cost ceiling exceeded', created_at: null, completed_at: null, content: null },
      error: undefined,
      isLoading: false,
    });

    const { result } = renderHook(() => useLesson('lsn_1'));

    expect(result.current.status).toBe('failed');
    expect(result.current.serverError).toBe('Cost ceiling exceeded');
  });

  it('polls via refreshInterval while non-terminal (queued/running), and stops once ready (S1-7)', () => {
    renderHook(() => useLesson('lsn_1'));

    const options = useSWRMock.mock.calls[0][2] as { refreshInterval: (data: unknown) => number };
    expect(options.refreshInterval({ status: 'running' })).toBeGreaterThan(0);
    expect(options.refreshInterval({ status: 'queued' })).toBeGreaterThan(0);
    expect(options.refreshInterval({ status: 'ready' })).toBe(0);
    expect(options.refreshInterval({ status: 'failed' })).toBe(0);
    expect(options.refreshInterval(undefined)).toBe(0);
  });
});
