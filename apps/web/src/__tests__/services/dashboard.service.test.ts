import { describe, it, expect, vi, beforeEach } from 'vitest';

const { getMock, getDashboardDataMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  getDashboardDataMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { get: getMock },
}));

vi.mock('@/mocks/api', () => ({
  dashboardApi: { getDashboardData: getDashboardDataMock },
}));

import { dashboardService } from '@/services/dashboard.service';
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

const PULSE = { streakDays: 3, weeklyMinutes: 42 };

beforeEach(() => {
  getMock.mockReset();
  getDashboardDataMock.mockReset();
  getDashboardDataMock.mockResolvedValue({ data: { learningPulse: PULSE } });
});

describe('dashboardService.getDashboard', () => {
  it('GETs content/lessons with a wide-enough window to find a ready lesson even if the newest few are still generating', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_1', status: 'running' }),
      lesson({ lesson_id: 'les_2', status: 'running' }),
    ];
    getMock.mockResolvedValue({ data: lessons });

    const data = await dashboardService.getDashboard();

    expect(getMock).toHaveBeenCalledWith('content/lessons', { params: { limit: 20 } });
    expect(data.recentLessons).toEqual(lessons.slice(0, 5));
  });

  it('picks the first ready lesson (already most-recent, backend orders by created_at desc) as continueLearning, even when it is not among the newest 6', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_running_1', status: 'running' }),
      lesson({ lesson_id: 'les_running_2', status: 'running' }),
      lesson({ lesson_id: 'les_running_3', status: 'running' }),
      lesson({ lesson_id: 'les_running_4', status: 'running' }),
      lesson({ lesson_id: 'les_running_5', status: 'running' }),
      lesson({ lesson_id: 'les_running_6', status: 'running' }),
      lesson({ lesson_id: 'les_ready', status: 'ready' }),
    ];
    getMock.mockResolvedValue({ data: lessons });

    const data = await dashboardService.getDashboard();

    expect(data.continueLearning?.lesson_id).toBe('les_ready');
  });

  it('continueLearning is null when there is no ready lesson yet', async () => {
    getMock.mockResolvedValue({ data: [lesson({ status: 'running' })] });

    const data = await dashboardService.getDashboard();

    expect(data.continueLearning).toBeNull();
  });

  it('excludes the continueLearning lesson from recentLessons so it does not render twice on the dashboard', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_ready', status: 'ready' }),
      lesson({ lesson_id: 'les_2', status: 'ready' }),
      lesson({ lesson_id: 'les_3', status: 'running' }),
    ];
    getMock.mockResolvedValue({ data: lessons });

    const data = await dashboardService.getDashboard();

    expect(data.continueLearning?.lesson_id).toBe('les_ready');
    expect(data.recentLessons.map((l) => l.lesson_id)).not.toContain('les_ready');
    expect(data.recentLessons.map((l) => l.lesson_id)).toEqual(['les_2', 'les_3']);
  });

  it('truncates recentLessons to 5 even when more lessons are available', async () => {
    const lessons = Array.from({ length: 8 }, (_, i) =>
      lesson({ lesson_id: `les_${i}`, status: 'running' })
    );
    getMock.mockResolvedValue({ data: lessons });

    const data = await dashboardService.getDashboard();

    expect(data.recentLessons).toHaveLength(5);
    expect(data.recentLessons.map((l) => l.lesson_id)).toEqual(['les_0', 'les_1', 'les_2', 'les_3', 'les_4']);
  });

  it('composes learningPulse from the existing mock (unrelated Dev 3 analytics domain, out of scope)', async () => {
    getMock.mockResolvedValue({ data: [] });

    const data = await dashboardService.getDashboard();

    expect(data.learningPulse).toEqual(PULSE);
  });

  it('still returns real lesson data when the unrelated mock pulse call fails', async () => {
    const lessons = [lesson({ lesson_id: 'les_1', status: 'running' })];
    getMock.mockResolvedValue({ data: lessons });
    getDashboardDataMock.mockRejectedValue(new Error('mock pulse unavailable'));

    const data = await dashboardService.getDashboard();

    expect(data.recentLessons).toEqual(lessons);
    expect(data.learningPulse).toBeUndefined();
  });

  it('propagates a real lesson-fetch failure (distinct from the mock pulse failing)', async () => {
    getMock.mockRejectedValue(new Error('lessons API down'));

    await expect(dashboardService.getDashboard()).rejects.toThrow('lessons API down');
  });
});
