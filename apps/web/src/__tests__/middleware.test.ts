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

// Builds a Supabase client stub for `.from('learner_dna').select(...).eq(...).maybeSingle()`.
function makeSupabaseStub(learnerDnaRow: { user_id: string } | null) {
  return {
    from: vi.fn(() => ({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          maybeSingle: vi.fn(async () => ({ data: learnerDnaRow, error: null })),
        })),
      })),
    })),
  };
}

// Simulates a Supabase query that resolves with a DB/RLS error (data: null, error set).
function makeSupabaseErrorStub() {
  return {
    from: vi.fn(() => ({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          maybeSingle: vi.fn(async () => ({ data: null, error: { message: 'db unreachable' } })),
        })),
      })),
    })),
  };
}

// Simulates a Supabase query that throws/rejects (network exception).
function makeSupabaseThrowingStub() {
  return {
    from: vi.fn(() => ({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          maybeSingle: vi.fn(async () => {
            throw new Error('network down');
          }),
        })),
      })),
    })),
  };
}

beforeEach(() => {
  updateSessionMock.mockReset();
});

describe('middleware — protected route coverage', () => {
  const PROTECTED_PATHS = ['/dashboard', '/library', '/upload', '/settings', '/onboarding', '/lesson/lsn_123'];
  const PUBLIC_PATHS = ['/', '/signin', '/signup', '/auth/callback'];

  it.each(PROTECTED_PATHS)('redirects %s to /signin when there is no session', async (path) => {
    updateSessionMock.mockResolvedValue({
      supabaseResponse: 'pass-through',
      user: null,
      supabase: makeSupabaseStub(null),
    });

    const response = await middleware(makeRequest(path));

    expect(response.status).toBe(307); // NextResponse.redirect default status
    expect(response.headers.get('location')).toBe(`http://localhost:3000/signin`);
  });

  it.each(PROTECTED_PATHS)('passes %s through when a session exists and onboarding is complete', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(PUBLIC_PATHS)('never redirects public path %s even without a session', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: null,
      supabase: makeSupabaseStub(null),
    });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });
});

describe('middleware — onboarding gate (learner_dna)', () => {
  const GATED_PATHS = ['/lesson/lsn_123', '/upload'];
  const UNGATED_PATHS = ['/dashboard', '/onboarding', '/library', '/settings'];

  it.each(GATED_PATHS)('redirects %s to /onboarding when the user has no learner_dna row', async (path) => {
    updateSessionMock.mockResolvedValue({
      supabaseResponse: { headers: new Headers() },
      user: { id: 'u1' },
      supabase: makeSupabaseStub(null),
    });

    const response = await middleware(makeRequest(path));

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('http://localhost:3000/onboarding');
  });

  it.each(GATED_PATHS)('passes %s through when the user has a learner_dna row', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(UNGATED_PATHS)('never redirects %s to /onboarding, even with no learner_dna row', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseStub(null),
    });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(GATED_PATHS)('fails open (passes %s through) when the learner_dna query resolves an error', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseErrorStub(),
    });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(GATED_PATHS)('fails open (passes %s through) when the learner_dna query throws', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseThrowingStub(),
    });

    const response = await middleware(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it('does not gate a sibling route sharing a prefix, e.g. /lessons (no trailing slash)', async () => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseStub(null),
    });

    const response = await middleware(makeRequest('/lessons'));

    expect(response).toBe(passThrough);
  });
});
