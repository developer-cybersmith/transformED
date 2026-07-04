import { describe, it, expect, vi, beforeEach } from 'vitest';

const { exchangeCodeForSessionMock, cookiesMock } = vi.hoisted(() => ({
  exchangeCodeForSessionMock: vi.fn(),
  cookiesMock: vi.fn(),
}));

vi.mock('@supabase/ssr', () => ({
  createServerClient: vi.fn(() => ({
    auth: { exchangeCodeForSession: exchangeCodeForSessionMock },
  })),
}));

vi.mock('next/headers', () => ({
  cookies: cookiesMock,
}));

import { GET } from '@/app/auth/callback/route';

function makeRequest(url: string): Request {
  return new Request(url);
}

beforeEach(() => {
  exchangeCodeForSessionMock.mockReset();
  cookiesMock.mockReset();
  cookiesMock.mockResolvedValue({ getAll: () => [], set: vi.fn() });
});

describe('GET /auth/callback', () => {
  it('exchanges the code and redirects to /dashboard by default', async () => {
    exchangeCodeForSessionMock.mockResolvedValue({ error: null });

    const response = await GET(makeRequest('https://app.example.com/auth/callback?code=abc123'));

    expect(response.headers.get('location')).toBe('https://app.example.com/dashboard');
    expect(exchangeCodeForSessionMock).toHaveBeenCalledWith('abc123');
  });

  it('redirects to a provided same-origin relative "next" path', async () => {
    exchangeCodeForSessionMock.mockResolvedValue({ error: null });

    const response = await GET(
      makeRequest('https://app.example.com/auth/callback?code=abc123&next=/lesson/lsn_1')
    );

    expect(response.headers.get('location')).toBe('https://app.example.com/lesson/lsn_1');
  });

  it('ignores a protocol-relative "next" param (open-redirect attempt) and falls back to /dashboard', async () => {
    exchangeCodeForSessionMock.mockResolvedValue({ error: null });

    const response = await GET(
      makeRequest('https://app.example.com/auth/callback?code=abc123&next=//evil.com')
    );

    expect(response.headers.get('location')).toBe('https://app.example.com/dashboard');
  });

  it('ignores a "next" param that is not a relative path (e.g. a bare host) and falls back to /dashboard', async () => {
    exchangeCodeForSessionMock.mockResolvedValue({ error: null });

    const response = await GET(
      makeRequest('https://app.example.com/auth/callback?code=abc123&next=%40evil.com')
    );

    expect(response.headers.get('location')).toBe('https://app.example.com/dashboard');
  });

  it('redirects to /signin?error=auth_callback_failed when the code exchange fails', async () => {
    exchangeCodeForSessionMock.mockResolvedValue({ error: new Error('invalid code') });

    const response = await GET(makeRequest('https://app.example.com/auth/callback?code=bad'));

    expect(response.headers.get('location')).toBe(
      'https://app.example.com/signin?error=auth_callback_failed'
    );
  });

  it('redirects to /signin?error=auth_callback_failed when no code is present', async () => {
    const response = await GET(makeRequest('https://app.example.com/auth/callback'));

    expect(response.headers.get('location')).toBe(
      'https://app.example.com/signin?error=auth_callback_failed'
    );
    expect(exchangeCodeForSessionMock).not.toHaveBeenCalled();
  });
});
