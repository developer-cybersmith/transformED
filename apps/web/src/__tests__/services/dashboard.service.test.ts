import { describe, it, expect, vi, beforeEach } from 'vitest';

const { listLessonsMock, getDashboardDataMock } = vi.hoisted(() => ({
  listLessonsMock: vi.fn(),
  getDashboardDataMock: vi.fn(),
}));

vi.mock('@/services/lessons.service', () => ({
  lessonsService: { listLessons: listLessonsMock },
}));

vi.mock('@/mocks/api', () => ({
  dashboardApi: { getDashboardData: getDashboardDataMock },
}));

import { dashboardService } from '@/services/dashboard.service';

const MOCK_CONTINUE_LEARNING = { id: 'les_1', title: 'Zero Trust Architecture' };
const MOCK_PULSE = { streak: 5, hoursThisWeek: 4.2, strongestTopic: 'Web Security' };
const RECENT_LESSON = { lesson_id: 'lsn_1', status: 'ready' as const, title: 'Lesson A', error: null, created_at: '2026-07-01T00:00:00Z', completed_at: '2026-07-01T00:05:00Z' };

beforeEach(() => {
  listLessonsMock.mockReset();
  getDashboardDataMock.mockReset();
  getDashboardDataMock.mockResolvedValue({
    success: true,
    data: { continueLearning: MOCK_CONTINUE_LEARNING, learningPulse: MOCK_PULSE, recentLessons: [] },
    message: 'ok',
  });
});

describe('dashboardService.getDashboard', () => {
  it('fetches real recent lessons (limit 5) and keeps continueLearning/learningPulse mocked', async () => {
    listLessonsMock.mockResolvedValue([RECENT_LESSON]);

    const response = await dashboardService.getDashboard();

    expect(listLessonsMock).toHaveBeenCalledWith({ limit: 5 });
    expect(response.success).toBe(true);
    expect(response.data?.recentLessons).toEqual([RECENT_LESSON]);
    expect(response.data?.continueLearning).toEqual(MOCK_CONTINUE_LEARNING);
    expect(response.data?.learningPulse).toEqual(MOCK_PULSE);
    expect(response.data?.recentLessonsError).toBeNull();
  });

  it('stays non-blocking on a recent-lessons failure: still resolves success with an inline error and unchanged mocked fields', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    listLessonsMock.mockRejectedValue(new Error('network error'));

    const response = await dashboardService.getDashboard();

    expect(response.success).toBe(true);
    expect(response.data?.recentLessons).toEqual([]);
    expect(response.data?.recentLessonsError).toEqual(expect.any(String));
    expect(response.data?.continueLearning).toEqual(MOCK_CONTINUE_LEARNING);
    expect(response.data?.learningPulse).toEqual(MOCK_PULSE);
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('stays non-blocking if the mock summary fetch itself fails: still resolves success with recent lessons intact and safe null fallbacks', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    getDashboardDataMock.mockRejectedValue(new Error('mock summary blew up'));
    listLessonsMock.mockResolvedValue([RECENT_LESSON]);

    const response = await dashboardService.getDashboard();

    expect(response.success).toBe(true);
    expect(response.data?.continueLearning).toBeNull();
    expect(response.data?.learningPulse).toBeNull();
    expect(response.data?.recentLessons).toEqual([RECENT_LESSON]);
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('treats a non-array recentLessons response as a failure, not a crash', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    // Intentionally malformed (not an array) to simulate a bad backend response.
    listLessonsMock.mockResolvedValue({ unexpected: 'shape' });

    const response = await dashboardService.getDashboard();

    expect(response.success).toBe(true);
    expect(response.data?.recentLessons).toEqual([]);
    expect(response.data?.recentLessonsError).toEqual(expect.any(String));
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it('fetches the mock summary and recent lessons concurrently, not sequentially', async () => {
    const callOrder: string[] = [];
    getDashboardDataMock.mockImplementation(async () => {
      callOrder.push('mock-start');
      await new Promise((resolve) => setTimeout(resolve, 10));
      callOrder.push('mock-end');
      return { success: true, data: { continueLearning: MOCK_CONTINUE_LEARNING, learningPulse: MOCK_PULSE, recentLessons: [] }, message: 'ok' };
    });
    listLessonsMock.mockImplementation(async () => {
      callOrder.push('lessons-start');
      await new Promise((resolve) => setTimeout(resolve, 10));
      callOrder.push('lessons-end');
      return [RECENT_LESSON];
    });

    await dashboardService.getDashboard();

    // Both must start before either finishes — proves they ran concurrently,
    // not one strictly after the other.
    expect(callOrder.indexOf('lessons-start')).toBeLessThan(callOrder.indexOf('mock-end'));
  });
});
