import { describe, it, expect, vi, beforeEach } from 'vitest';

const { createClientMock, getSessionMock, getUserMock } = vi.hoisted(() => ({
  createClientMock: vi.fn(),
  getSessionMock: vi.fn(),
  getUserMock: vi.fn(),
}));

vi.mock('@/lib/supabase/server', () => ({
  createClient: createClientMock,
}));

import { getServerApi } from '@/lib/api.server';

beforeEach(() => {
  createClientMock.mockReset();
  getSessionMock.mockReset();
  getUserMock.mockReset();
  createClientMock.mockResolvedValue({ auth: { getSession: getSessionMock, getUser: getUserMock } });
});

describe('getServerApi', () => {
  it('attaches Authorization when getUser() confirms a valid user and a session token exists', async () => {
    getUserMock.mockResolvedValue({ data: { user: { id: 'user_1' } }, error: null });
    getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok_123' } } });

    const api = await getServerApi();

    expect(api.defaults.headers.common.Authorization).toBe('Bearer tok_123');
  });

  it('omits Authorization when there is no server-side session', async () => {
    getUserMock.mockResolvedValue({ data: { user: { id: 'user_1' } }, error: null });
    getSessionMock.mockResolvedValue({ data: { session: null } });

    const api = await getServerApi();

    expect(api.defaults.headers.common.Authorization).toBeUndefined();
  });

  it('omits Authorization if getUser() fails validation even when a session cookie is present (getSession() alone is not revalidated)', async () => {
    getUserMock.mockResolvedValue({ data: { user: null }, error: new Error('invalid or expired') });
    getSessionMock.mockResolvedValue({ data: { session: { access_token: 'tok_stale' } } });

    const api = await getServerApi();

    expect(api.defaults.headers.common.Authorization).toBeUndefined();
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it('uses the same baseURL as the client-side api instance', async () => {
    getUserMock.mockResolvedValue({ data: { user: null }, error: null });
    getSessionMock.mockResolvedValue({ data: { session: null } });

    const api = await getServerApi();

    expect(api.defaults.baseURL).toBe(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api');
  });
});
