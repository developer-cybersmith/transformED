import { describe, it, expect, vi, beforeEach } from 'vitest';

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock('@/lib/api', () => ({
  api: { get: getMock },
}));

import { libraryService } from '@/services/library.service';
import type { LessonStatusResponse } from '@/services/upload.service';

function lesson(overrides: Partial<LessonStatusResponse>): LessonStatusResponse {
  return {
    lesson_id: 'les_1',
    status: 'ready',
    title: 'SQL Injection Vectors',
    error: null,
    created_at: '2026-07-24T10:00:00Z',
    completed_at: '2026-07-24T10:05:00Z',
    content: null,
    ...overrides,
  };
}

beforeEach(() => {
  getMock.mockReset();
});

describe('libraryService.getLibrary', () => {
  it('GETs content/lessons and buckets by real status — queued and running both bucket into processing', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_ready', status: 'ready' }),
      lesson({ lesson_id: 'les_running', status: 'running' }),
      lesson({ lesson_id: 'les_queued', status: 'queued' }),
      lesson({ lesson_id: 'les_failed', status: 'failed' }),
    ];
    getMock.mockResolvedValue({ data: lessons });

    const data = await libraryService.getLibrary();

    expect(getMock).toHaveBeenCalledWith('content/lessons', { params: { limit: 100 } });
    expect(data.ready.map((l) => l.lesson_id)).toEqual(['les_ready']);
    expect(data.processing.map((l) => l.lesson_id)).toEqual(['les_running', 'les_queued']);
    expect(data.failed.map((l) => l.lesson_id)).toEqual(['les_failed']);
  });

  it('also returns the raw, unfiltered list — so a future unrecognized status can never silently vanish from "All"', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_ready', status: 'ready' }),
      lesson({ lesson_id: 'les_running', status: 'running' }),
      lesson({ lesson_id: 'les_queued', status: 'queued' }),
      lesson({ lesson_id: 'les_failed', status: 'failed' }),
    ];
    getMock.mockResolvedValue({ data: lessons });

    const data = await libraryService.getLibrary();

    expect(data.all).toEqual(lessons);
  });

  it('preserves order and all entries when a bucket has more than one lesson', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_running_1', status: 'running' }),
      lesson({ lesson_id: 'les_queued_1', status: 'queued' }),
      lesson({ lesson_id: 'les_running_2', status: 'running' }),
    ];
    getMock.mockResolvedValue({ data: lessons });

    const data = await libraryService.getLibrary();

    expect(data.processing.map((l) => l.lesson_id)).toEqual(['les_running_1', 'les_queued_1', 'les_running_2']);
  });

  it('returns empty buckets, not an error, when the account has no lessons yet', async () => {
    getMock.mockResolvedValue({ data: [] });

    const data = await libraryService.getLibrary();

    expect(data).toEqual({ all: [], ready: [], processing: [], failed: [] });
  });
});
