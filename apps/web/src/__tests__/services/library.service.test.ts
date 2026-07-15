import { describe, it, expect, vi, beforeEach } from 'vitest';

const { listLessonsMock } = vi.hoisted(() => ({ listLessonsMock: vi.fn() }));

vi.mock('@/services/lessons.service', () => ({
  lessonsService: { listLessons: listLessonsMock },
}));

import { libraryService } from '@/services/library.service';

const LESSON = { lesson_id: 'lsn_1', status: 'ready' as const, title: 'Lesson A', error: null, created_at: '2026-07-01T00:00:00Z', completed_at: '2026-07-01T00:05:00Z' };

beforeEach(() => {
  listLessonsMock.mockReset();
});

describe('libraryService.getLibrary', () => {
  it('fetches the first page (limit 24, offset 0) and returns it wrapped as a success response', async () => {
    listLessonsMock.mockResolvedValue([LESSON]);

    const response = await libraryService.getLibrary();

    expect(listLessonsMock).toHaveBeenCalledWith({ limit: 24, offset: 0 });
    expect(response.success).toBe(true);
    expect(response.data).toEqual({ lessons: [LESSON] });
  });

  it('returns a failure response instead of throwing when the fetch fails', async () => {
    listLessonsMock.mockRejectedValue(new Error('network error'));

    const response = await libraryService.getLibrary();

    expect(response.success).toBe(false);
    expect(response.data).toBeNull();
  });
});
