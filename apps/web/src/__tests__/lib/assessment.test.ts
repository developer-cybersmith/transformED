import { describe, it, expect, vi, beforeEach } from 'vitest';

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock('@/lib/api', () => ({
  api: { get: apiGetMock },
}));

import { getSessionReport } from '@/lib/assessment';

beforeEach(() => {
  apiGetMock.mockReset();
  apiGetMock.mockResolvedValue({ data: { session_id: 'sess_1' } });
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
