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

  it('returns the fetched lesson and stops loading', async () => {
    useSWRMock.mockReturnValue({ data: { lesson_id: 'lsn_1' }, error: undefined, isLoading: false });

    const { result } = renderHook(() => useLesson('lsn_1'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.lesson).toEqual({ lesson_id: 'lsn_1' });
  });
});
