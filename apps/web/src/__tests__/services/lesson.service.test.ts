import { describe, it, expect, vi, beforeEach } from 'vitest';

const { getMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { get: getMock },
}));

const { getLessonByIdMock, getLessonPackageByIdMock, updateLessonProgressMock } = vi.hoisted(() => ({
  getLessonByIdMock: vi.fn(),
  getLessonPackageByIdMock: vi.fn(),
  updateLessonProgressMock: vi.fn(),
}));

vi.mock('@/mocks/api', () => ({
  lessonApi: {
    getLessonById: getLessonByIdMock,
    getLessonPackageById: getLessonPackageByIdMock,
    updateLessonProgress: updateLessonProgressMock,
  },
}));

import { lessonService } from '@/services/lesson.service';

beforeEach(() => {
  getMock.mockReset();
  getLessonByIdMock.mockReset();
  getLessonPackageByIdMock.mockReset();
  updateLessonProgressMock.mockReset();
});

describe('lessonService.getLessonPackage', () => {
  it('calls the real GET /content/lessons/{id} endpoint via the authenticated api client (S1-7)', async () => {
    const responseData = {
      lesson_id: 'lsn_1',
      status: 'ready',
      title: 'Real Lesson',
      error: null,
      created_at: '2026-07-23T00:00:00Z',
      completed_at: '2026-07-23T00:05:00Z',
      content: { lesson_id: 'lsn_1' },
    };
    getMock.mockResolvedValue({ data: responseData });

    const result = await lessonService.getLessonPackage('lsn_1');

    expect(getMock).toHaveBeenCalledWith('content/lessons/lsn_1');
    expect(result.data).toEqual(responseData);
  });

  it('never falls back to the mock lessonApi (S1-7 — mock wiring retired)', async () => {
    getMock.mockResolvedValue({ data: { lesson_id: 'lsn_1', status: 'ready', content: null } });

    await lessonService.getLessonPackage('lsn_1');

    expect(getLessonPackageByIdMock).not.toHaveBeenCalled();
  });

  it('propagates rejection (e.g. 404/network error) instead of swallowing it', async () => {
    const error = { response: { status: 404 } };
    getMock.mockRejectedValue(error);

    await expect(lessonService.getLessonPackage('missing')).rejects.toBe(error);
  });
});

describe('lessonService — untouched mock-backed functions (AC-7)', () => {
  it('getLesson still delegates to the mock lessonApi (no real backend yet)', () => {
    lessonService.getLesson('lsn_1');

    expect(getLessonByIdMock).toHaveBeenCalledWith('lsn_1');
  });

  it('updateProgress still delegates to the mock lessonApi (no real backend yet)', () => {
    lessonService.updateProgress('lsn_1', 42);

    expect(updateLessonProgressMock).toHaveBeenCalledWith('lsn_1', 42);
  });
});
