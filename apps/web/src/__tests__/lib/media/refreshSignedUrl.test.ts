/**
 * Exercised through the real HTTP contract via MSW, not a `vi.mock('@/lib/api')` --
 * per DEFECT-REGISTER binding rule 2, a module mock could not disconfirm the real
 * axios instance, its baseURL resolution, or its auth interceptor.
 *
 * Fixtures use `http://localhost:54321` as the origin -- the same
 * `NEXT_PUBLIC_SUPABASE_URL` value `src/test/setup.ts` sets for the whole
 * suite -- so `parseSignedUrl`'s origin check (review finding) matches the
 * configured project in every test here without per-test env stubbing.
 */
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
import { parseSignedUrl, refreshSignedUrl } from '@/lib/media/refreshSignedUrl';

const REAL_SIGNED_URL =
  'http://localhost:54321/storage/v1/object/sign/lesson-audio/abc-123/seg-1.mp3?token=old-expired-token';

describe('parseSignedUrl', () => {
  it('extracts bucket and path from a real Supabase signed URL', () => {
    expect(parseSignedUrl(REAL_SIGNED_URL)).toEqual({
      bucket: 'lesson-audio',
      path: 'abc-123/seg-1.mp3',
    });
  });

  it('returns null for a URL with no /storage/v1/object/sign/ segment', () => {
    expect(parseSignedUrl('http://localhost:54321/not-a-signed-url.mp3')).toBeNull();
  });

  it('returns null for an empty string', () => {
    expect(parseSignedUrl('')).toBeNull();
  });

  it('returns null for a non-Supabase host that happens to share the path shape (review finding: origin must match the configured project)', () => {
    expect(
      parseSignedUrl('https://evil.example.com/storage/v1/object/sign/lesson-audio/x.mp3?token=t'),
    ).toBeNull();
  });

  it('returns null for a malformed percent-encoding in the path', () => {
    expect(parseSignedUrl('http://localhost:54321/storage/v1/object/sign/b/%E0%A4%A%3F')).toBeNull();
  });

  it('returns null for a not-actually-a-URL string', () => {
    expect(parseSignedUrl('://not a url at all')).toBeNull();
  });
});

describe('refreshSignedUrl', () => {
  it('returns null immediately for a malformed URL, without making a network call', async () => {
    let called = false;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        called = true;
        return HttpResponse.json({ signed_url: 'https://fresh', expires_in: 3600 });
      }),
    );

    const result = await refreshSignedUrl('not-a-signed-url');

    expect(result).toBeNull();
    expect(called).toBe(false);
  });

  it('returns null immediately for a wrong-host URL, without making a network call (review finding)', async () => {
    let called = false;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        called = true;
        return HttpResponse.json({ signed_url: 'https://fresh', expires_in: 3600 });
      }),
    );

    const result = await refreshSignedUrl(
      'https://evil.example.com/storage/v1/object/sign/lesson-audio/x.mp3?token=t',
    );

    expect(result).toBeNull();
    expect(called).toBe(false);
  });

  it('calls GET /api/media/signed-url with the parsed bucket/path and an 8-hour expires_in, returning the fresh URL', async () => {
    let seenParams: { bucket: string | null; path: string | null; expires_in: string | null } | null = null;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, ({ request }) => {
        const url = new URL(request.url);
        seenParams = {
          bucket: url.searchParams.get('bucket'),
          path: url.searchParams.get('path'),
          expires_in: url.searchParams.get('expires_in'),
        };
        return HttpResponse.json({ signed_url: 'https://project.supabase.co/fresh-signed', expires_in: 28800 });
      }),
    );

    const result = await refreshSignedUrl(REAL_SIGNED_URL);

    // Matches _EMBEDDED_MEDIA_EXPIRY_S (apps/api/app/modules/content/router.py) --
    // omitting this would silently inherit the backend's 1-hour default instead
    // (review finding, Scale & Load Hunter).
    expect(seenParams).toEqual({ bucket: 'lesson-audio', path: 'abc-123/seg-1.mp3', expires_in: '28800' });
    expect(result).toBe('https://project.supabase.co/fresh-signed');
  });

  it('returns null (never throws) when the backend 404s the storage object', async () => {
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () =>
        HttpResponse.json({ detail: 'Storage object not found' }, { status: 404 }),
      ),
    );

    await expect(refreshSignedUrl(REAL_SIGNED_URL)).resolves.toBeNull();
  });

  it('returns null (never throws) on a network error', async () => {
    server.use(http.get(`${API_BASE}/media/signed-url`, () => HttpResponse.error()));

    await expect(refreshSignedUrl(REAL_SIGNED_URL)).resolves.toBeNull();
  });

  it('returns null (not the empty string) when the backend responds 200 with an empty signed_url (review finding)', async () => {
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => HttpResponse.json({ signed_url: '', expires_in: 28800 })),
    );

    await expect(refreshSignedUrl(REAL_SIGNED_URL)).resolves.toBeNull();
  });
});
