import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';

const { updateSessionMock } = vi.hoisted(() => ({
  updateSessionMock: vi.fn(),
}));

vi.mock('@/lib/supabase/middleware', () => ({
  updateSession: updateSessionMock,
}));

// Imported after the mock so the module under test picks it up.
import { middleware } from '@/middleware';

function makeRequest(pathname: string): NextRequest {
  return new NextRequest(new URL(pathname, 'http://localhost:3000'));
}

beforeEach(() => {
  updateSessionMock.mockReset();
});

describe('middleware — protected route coverage', () => {
  const PROTECTED_PATHS = ['/dashboard', '/library', '/upload', '/settings', '/onboarding', '/lesson/lsn_123'];
  const PUBLIC_PATHS = ['/', '/signin', '/signup', '/auth/callback'];

  it.each(PROTECTED_PATHS)('redirects %s to /signin when there is no session', async (path) => {
    updateSessionMock.mockResolvedValue({ supabaseResponse: 'pass-through', user: null });

    const response = await middleware(makeRequest(path));

    expect(response.status).toBe(307); // NextResponse.redirect default status
    expect(response.headers.get('location')).toBe(`http://localhost:3000/signin`);
  });

  it.each(PROTECTED_PATHS)('passes %s through when a session exists', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({ supabaseResponse: passThrough, user: { id: 'u1' } });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(PUBLIC_PATHS)('never redirects public path %s even without a session', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({ supabaseResponse: passThrough, user: null });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });
});
