import { describe, it, expect, vi, beforeEach } from 'vitest';

const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { get: apiGetMock, post: apiPostMock },
}));

import {
  completeSession,
  createSession,
  getSessionReport,
  listSessions,
  submitQuiz,
  submitTeachBack,
} from '@/lib/assessment';

beforeEach(() => {
  apiGetMock.mockReset();
  apiGetMock.mockResolvedValue({ data: { session_id: 'sess_1' } });
  apiPostMock.mockReset();
});

describe('getSessionReport', () => {
  it('URL-encodes the sessionId before interpolating it into the request path', async () => {
    await getSessionReport('sess/1?evil=true');

    expect(apiGetMock).toHaveBeenCalledWith(
      `/assessment/session/${encodeURIComponent('sess/1?evil=true')}/report`
    );
  });

  it('calls the real endpoint with a normal id', async () => {
    await getSessionReport('sess_abc123');

    expect(apiGetMock).toHaveBeenCalledWith('/assessment/session/sess_abc123/report');
  });

  it('passes through ces_timeline and intervention_events unchanged (Story 2-46/S3-05)', async () => {
    const responseData = {
      session_id: 'sess_abc123',
      ces_timeline: [{ minute: 0, ces: 60 }, { minute: 1, ces: 70 }],
      intervention_events: [{ minute: 3, type: 'distraction' }],
    };
    apiGetMock.mockResolvedValue({ data: responseData });

    const result = await getSessionReport('sess_abc123');

    expect(result.ces_timeline).toEqual(responseData.ces_timeline);
    expect(result.intervention_events).toEqual(responseData.intervention_events);
  });

  it('passes through teachback_details unchanged (Story 2-48/S3-06)', async () => {
    const responseData = {
      session_id: 'sess_abc123',
      teachback_details: [
        {
          segment_id: 'seg_001',
          score: 85,
          feedback_praise: 'Nice work.',
          feedback_correction: null,
          concepts_hit: ['mitochondria'],
          concepts_missed: [],
          attempt_number: 1,
        },
      ],
    };
    apiGetMock.mockResolvedValue({ data: responseData });

    const result = await getSessionReport('sess_abc123');

    expect(result.teachback_details).toEqual(responseData.teachback_details);
  });
});

describe('listSessions (Story 2-58/BR-7)', () => {
  it('calls the real GET /assessment/sessions endpoint and returns the response data unchanged', async () => {
    const responseData = [
      {
        session_id: 'sess_1',
        lesson_id: 'lesson_1',
        lesson_title: 'Photosynthesis',
        tier: 'T1',
        tier_label: 'Full-Depth',
        started_at: '2026-09-01T10:00:00Z',
        ended_at: '2026-09-01T10:20:00Z',
        completed: true,
        ces_score: 82,
      },
    ];
    apiGetMock.mockResolvedValue({ data: responseData });

    const result = await listSessions();

    expect(apiGetMock).toHaveBeenCalledWith('/assessment/sessions');
    expect(result).toEqual(responseData);
  });

  it('propagates a rejected request rather than swallowing it', async () => {
    apiGetMock.mockRejectedValue(new Error('network down'));

    await expect(listSessions()).rejects.toThrow('network down');
  });
});

describe('submitQuiz', () => {
  it('posts the exact payload to the real endpoint and returns the response data unchanged', async () => {
    const payload = {
      session_id: 'sess_1',
      lesson_id: 'lesson_1',
      segment_id: 'seg_1',
      answers: [{ question_id: 'q_1', response_index: 2, response_time_ms: 1500 }],
    };
    const responseData = {
      session_id: 'sess_1',
      score: 75,
      correct_count: 3,
      total_count: 4,
      ces_contribution: 0.75,
      feedback: [],
    };
    apiPostMock.mockResolvedValue({ data: responseData });

    const result = await submitQuiz(payload);

    expect(apiPostMock).toHaveBeenCalledWith('/assessment/quiz', payload);
    expect(result).toEqual(responseData);
  });
});

describe('createSession (D18/Story 2-39)', () => {
  it('posts {lesson_id} only -- session_id/started_at are never client-sent, matching the DB-generated schema', async () => {
    const responseData = { session_id: 'sess_real_1', lesson_id: 'lesson_1', started_at: '2026-07-30T00:00:00Z' };
    apiPostMock.mockResolvedValue({ data: responseData });

    const result = await createSession({ lesson_id: 'lesson_1' });

    expect(apiPostMock).toHaveBeenCalledWith('/assessment/sessions', { lesson_id: 'lesson_1' });
    expect(result).toEqual(responseData);
  });

  it('propagates a rejected request rather than swallowing it -- the caller (Player.tsx) decides how to handle failure', async () => {
    apiPostMock.mockRejectedValue(new Error('network down'));

    await expect(createSession({ lesson_id: 'lesson_1' })).rejects.toThrow('network down');
  });
});

describe('completeSession', () => {
  it('URL-encodes the sessionId and posts no body, returning the response data unchanged', async () => {
    const responseData = { session_id: 'sess/1?evil=true', ended_at: '2026-08-12T12:00:00Z' };
    apiPostMock.mockResolvedValue({ data: responseData });

    const result = await completeSession('sess/1?evil=true');

    expect(apiPostMock).toHaveBeenCalledWith(
      `/assessment/session/${encodeURIComponent('sess/1?evil=true')}/complete`
    );
    expect(result).toEqual(responseData);
  });

  it('propagates a rejected request rather than swallowing it -- the caller (Player.tsx) decides how to handle failure', async () => {
    apiPostMock.mockRejectedValue(new Error('network down'));

    await expect(completeSession('sess_1')).rejects.toThrow('network down');
  });
});

describe('submitTeachBack', () => {
  it('posts the exact payload to the real endpoint and returns the response data unchanged', async () => {
    const payload = {
      session_id: 'sess_1',
      lesson_id: 'lesson_1',
      segment_id: 'seg_1',
      response_text: 'It terminates the query early.',
    };
    const responseData = {
      session_id: 'sess_1',
      rubric_scores: { accuracy: 'Strong', completeness: 'Developing', clarity: 'Strong' },
      overall_score: 82,
      ces_contribution: 0.82,
      feedback: 'Nice explanation!',
    };
    apiPostMock.mockResolvedValue({ data: responseData });

    const result = await submitTeachBack(payload);

    expect(apiPostMock).toHaveBeenCalledWith('/assessment/teachback', payload);
    expect(result).toEqual(responseData);
  });
});
