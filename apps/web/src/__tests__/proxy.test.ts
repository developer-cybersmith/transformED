import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextRequest } from 'next/server';

const { updateSessionMock } = vi.hoisted(() => ({
  updateSessionMock: vi.fn(),
}));

vi.mock('@/lib/supabase/middleware', () => ({
  updateSession: updateSessionMock,
}));

// Imported after the mock so the module under test picks it up.
import { proxy } from '@/proxy';

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
  // Every existing test below predates the beta-access gate and expects a
  // logged-in user to pass through to the onboarding-gate/protected-route
  // logic under test -- stub the allowlist to include the standard test
  // user so those assertions aren't incidentally testing the new gate too.
  // Tests for the gate itself override this per-test.
  vi.stubEnv('APPROVED_EMAILS', 'u1@example.com');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('proxy — beta access gate (APPROVED_EMAILS)', () => {
  const PROTECTED_PATHS = ['/dashboard', '/library', '/upload', '/settings', '/onboarding', '/lesson/lsn_123'];

  it.each(PROTECTED_PATHS)('redirects %s to /pending-approval when the email is not on the allowlist', async (path) => {
    vi.stubEnv('APPROVED_EMAILS', 'someone-else@example.com');
    updateSessionMock.mockResolvedValue({
      supabaseResponse: { headers: new Headers() },
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await proxy(makeRequest(path));

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('http://localhost:3000/pending-approval');
  });

  it('fails CLOSED (redirects), not open, when APPROVED_EMAILS is unset entirely', async () => {
    vi.stubEnv('APPROVED_EMAILS', '');
    updateSessionMock.mockResolvedValue({
      supabaseResponse: { headers: new Headers() },
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await proxy(makeRequest('/dashboard'));

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('http://localhost:3000/pending-approval');
  });

  it('matches case-insensitively against the JWT email claim', async () => {
    vi.stubEnv('APPROVED_EMAILS', 'U1@Example.com');
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await proxy(makeRequest('/dashboard'));

    expect(response).toBe(passThrough);
  });

  it('never redirects /pending-approval itself, even when not approved (would otherwise loop)', async () => {
    vi.stubEnv('APPROVED_EMAILS', 'someone-else@example.com');
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest('/pending-approval'));

    expect(response).toBe(passThrough);
  });

  it('does not redirect an unauthenticated request to /pending-approval — /signin takes priority', async () => {
    vi.stubEnv('APPROVED_EMAILS', '');
    updateSessionMock.mockResolvedValue({
      supabaseResponse: 'pass-through',
      user: null,
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest('/dashboard'));

    expect(response.headers.get('location')).toBe('http://localhost:3000/signin');
  });
});

describe('middleware — protected route coverage', () => {
  const PROTECTED_PATHS = ['/dashboard', '/library', '/upload', '/settings', '/onboarding', '/lesson/lsn_123', '/books', '/books/dfea46ac-1c6e-401a-a936-269eedd3e5d9'];
  const PUBLIC_PATHS = ['/', '/signin', '/signup', '/auth/callback'];

  it.each(PROTECTED_PATHS)('redirects %s to /signin when there is no session', async (path) => {
    updateSessionMock.mockResolvedValue({
      supabaseResponse: 'pass-through',
      user: null,
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest(path));

    expect(response.status).toBe(307); // NextResponse.redirect default status
    expect(response.headers.get('location')).toBe(`http://localhost:3000/signin`);
  });

  it.each(PROTECTED_PATHS)('passes %s through when a session exists and onboarding is complete', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await proxy(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(PUBLIC_PATHS)('never redirects public path %s even without a session', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: null,
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest(path));

    expect(response).toBe(passThrough);
  });
});

describe('middleware — onboarding gate (learner_dna)', () => {
  // W2 AC8: /books is onboarding-gated. One entry covers both the list and the
  // detail route because pathRequiresOnboarding matches on exact segments.
  const GATED_PATHS = ['/lesson/lsn_123', '/upload', '/books', '/books/dfea46ac-1c6e-401a-a936-269eedd3e5d9'];
  const UNGATED_PATHS = ['/dashboard', '/onboarding', '/library', '/settings'];

  it.each(GATED_PATHS)('redirects %s to /onboarding when the user has no learner_dna row', async (path) => {
    updateSessionMock.mockResolvedValue({
      supabaseResponse: { headers: new Headers() },
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest(path));

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('http://localhost:3000/onboarding');
  });

  it.each(GATED_PATHS)('passes %s through when the user has a learner_dna row', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub({ user_id: 'u1' }),
    });

    const response = await proxy(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(UNGATED_PATHS)('never redirects %s to /onboarding, even with no learner_dna row', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(GATED_PATHS)('fails open (passes %s through) when the learner_dna query resolves an error', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseErrorStub(),
    });

    const response = await proxy(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it.each(GATED_PATHS)('fails open (passes %s through) when the learner_dna query throws', async (path) => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseThrowingStub(),
    });

    const response = await proxy(makeRequest(path));

    expect(response).toBe(passThrough);
  });

  it('does not gate a sibling route sharing the /books prefix, e.g. /bookstore', async () => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1' },
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest('/bookstore'));

    expect(response).toBe(passThrough);
  });

  it('does not gate a sibling route sharing a prefix, e.g. /lessons (no trailing slash)', async () => {
    const passThrough = { headers: new Headers() } as unknown;
    updateSessionMock.mockResolvedValue({
      supabaseResponse: passThrough,
      user: { id: 'u1', email: 'u1@example.com' },
      supabase: makeSupabaseStub(null),
    });

    const response = await proxy(makeRequest('/lessons'));

    expect(response).toBe(passThrough);
  });
});
