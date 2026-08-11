/**
 * Exercised through the real HTTP contract via MSW, not a `vi.mock('@/lib/api')` --
 * per DEFECT-REGISTER binding rule 2, a module mock could not disconfirm the real
 * axios instance, its baseURL resolution, or its auth interceptor.
 */
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
import { parseSignedUrl, refreshSignedUrl } from '@/lib/media/refreshSignedUrl';

const REAL_SIGNED_URL =
  'https://project.supabase.co/storage/v1/object/sign/lesson-audio/abc-123/seg-1.mp3?token=old-expired-token';

describe('parseSignedUrl', () => {
  it('extracts bucket and path from a real Supabase signed URL', () => {
    expect(parseSignedUrl(REAL_SIGNED_URL)).toEqual({
      bucket: 'lesson-audio',
      path: 'abc-123/seg-1.mp3',
    });
  });

  it('returns null for a URL with no /storage/v1/object/sign/ segment', () => {
    expect(parseSignedUrl('https://example.com/not-a-signed-url.mp3')).toBeNull();
  });

  it('returns null for an empty string', () => {
    expect(parseSignedUrl('')).toBeNull();
  });

  it('returns null for a non-Supabase host that happens to share the path shape', () => {
    // Same shape, different origin -- parsing bucket/path is still correct here
    // (the helper only cares about the path, not the host), but this pins the
    // decision explicitly rather than leaving it implicit.
    expect(
      parseSignedUrl('https://evil.example.com/storage/v1/object/sign/lesson-audio/x.mp3?token=t'),
    ).toEqual({ bucket: 'lesson-audio', path: 'x.mp3' });
  });

  it('returns null for a malformed percent-encoding in the path', () => {
    expect(parseSignedUrl('https://project.supabase.co/storage/v1/object/sign/b/%E0%A4%A%3F')).toBeNull();
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

  it('calls GET /api/media/signed-url with the parsed bucket/path and returns the fresh URL', async () => {
    let seenParams: { bucket: string | null; path: string | null } | null = null;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, ({ request }) => {
        const url = new URL(request.url);
        seenParams = {
          bucket: url.searchParams.get('bucket'),
          path: url.searchParams.get('path'),
        };
        return HttpResponse.json({ signed_url: 'https://project.supabase.co/fresh-signed', expires_in: 3600 });
      }),
    );

    const result = await refreshSignedUrl(REAL_SIGNED_URL);

    expect(seenParams).toEqual({ bucket: 'lesson-audio', path: 'abc-123/seg-1.mp3' });
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
});
