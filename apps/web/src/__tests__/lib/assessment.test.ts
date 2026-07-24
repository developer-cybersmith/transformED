import { describe, it, expect, vi, beforeEach } from 'vitest';

const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { get: apiGetMock, post: apiPostMock },
}));

import { getSessionReport, submitQuiz, submitTeachBack } from '@/lib/assessment';

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
