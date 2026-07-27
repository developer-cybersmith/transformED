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
  it('GETs content/lessons and returns the real, unwrapped lesson data', async () => {
    const lessons = [lesson({ lesson_id: 'les_1' }), lesson({ lesson_id: 'les_2' })];
    getMock.mockResolvedValue({ data: lessons });

    const data = await dashboardService.getDashboard();

    expect(getMock).toHaveBeenCalledWith('content/lessons', { params: { limit: 6 } });
    expect(data.recentLessons).toEqual(lessons.slice(0, 5));
  });

  it('picks the first ready lesson (already most-recent, backend orders by created_at desc) as continueLearning', async () => {
    const lessons = [
      lesson({ lesson_id: 'les_processing', status: 'running' }),
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

  it('composes learningPulse from the existing mock (unrelated Dev 3 analytics domain, out of scope)', async () => {
    getMock.mockResolvedValue({ data: [] });

    const data = await dashboardService.getDashboard();

    expect(data.learningPulse).toEqual(PULSE);
  });
});
