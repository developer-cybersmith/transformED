import { describe, it, expect, vi, beforeEach } from 'vitest';

const { getServerApiMock, getMock } = vi.hoisted(() => ({
  getServerApiMock: vi.fn(),
  getMock: vi.fn(),
}));

vi.mock('@/lib/api.server', () => ({
  getServerApi: getServerApiMock,
}));

import { lessonsService } from '@/services/lessons.service';

const LESSON_A = { lesson_id: 'lsn_1', status: 'ready' as const, title: 'Lesson A', error: null, created_at: '2026-07-01T00:00:00Z', completed_at: '2026-07-01T00:05:00Z' };
const LESSON_B = { lesson_id: 'lsn_2', status: 'running' as const, title: null, error: null, created_at: '2026-07-02T00:00:00Z', completed_at: null };

beforeEach(() => {
  getServerApiMock.mockReset();
  getMock.mockReset();
  getServerApiMock.mockResolvedValue({ get: getMock });
});

describe('lessonsService.listLessons', () => {
  it('calls GET content/lessons with the given limit/offset and returns the array', async () => {
    getMock.mockResolvedValue({ data: [LESSON_A, LESSON_B] });

    const result = await lessonsService.listLessons({ limit: 24, offset: 0 });

    expect(getMock).toHaveBeenCalledWith('content/lessons', { params: { limit: 24, offset: 0 } });
    expect(result).toEqual([LESSON_A, LESSON_B]);
  });

  it('defaults to limit=20, offset=0 when called with no args', async () => {
    getMock.mockResolvedValue({ data: [] });

    await lessonsService.listLessons();

    expect(getMock).toHaveBeenCalledWith('content/lessons', { params: { limit: 20, offset: 0 } });
  });
});
