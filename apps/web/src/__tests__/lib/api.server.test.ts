import { describe, it, expect, vi, beforeEach } from 'vitest';

const { createClientMock, getSessionMock } = vi.hoisted(() => ({
  createClientMock: vi.fn(),
  getSessionMock: vi.fn(),
}));

vi.mock('@/lib/supabase/server', () => ({
  createClient: createClientMock,
}));

import { getServerApi } from '@/lib/api.server';

beforeEach(() => {
  createClientMock.mockReset();
  getSessionMock.mockReset();
  createClientMock.mockResolvedValue({ auth: { getSession: getSessionMock } });
});

describe('getServerApi', () => {
  it('attaches Authorization from the server-side session when one exists', async () => {
    getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok_123' } } });

    const api = await getServerApi();

    expect(api.defaults.headers.common.Authorization).toBe('Bearer tok_123');
  });

  it('omits Authorization when there is no server-side session', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });

    const api = await getServerApi();

    expect(api.defaults.headers.common.Authorization).toBeUndefined();
  });

  it('uses the same baseURL as the client-side api instance', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });

    const api = await getServerApi();

    expect(api.defaults.baseURL).toBe(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api');
  });
});
