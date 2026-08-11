import { api } from '@/lib/api';

/**
 * Matches Supabase Storage's signed-URL path shape:
 * `.../storage/v1/object/sign/{bucket}/{path}?token=...`. The raw storage
 * path never reaches the frontend separately -- `_resolve_lesson_content`
 * (apps/api/app/modules/content/router.py) overwrites it with the signed
 * URL before the response leaves the server -- so this is the only way to
 * recover {bucket, path} without an apps/api change (Story 2-45).
 */
const SIGNED_URL_SHAPE = /\/storage\/v1\/object\/sign\/([^/]+)\/([^?]+)/;

// Mirrors apps/api/app/modules/content/router.py's `_EMBEDDED_MEDIA_EXPIRY_S`
// (8h). Passed explicitly on every re-sign -- omitting it would silently
// fall back to the backend's 1-hour Query default, an 8x-shorter re-signed
// lifetime than the window this whole feature exists to restore (review
// finding, Scale & Load Hunter).
const RESIGN_EXPIRY_S = 8 * 60 * 60;

export interface ParsedSignedUrl {
  bucket: string;
  path: string;
}

/**
 * Extracts {bucket, path} from a Supabase signed URL. Returns null for any
 * URL that doesn't match the expected shape, whose origin isn't the
 * configured Supabase project (review finding -- the path-shape regex alone
 * would accept a same-shaped URL from any host), or whose path segment is
 * not valid percent-encoding -- callers must never throw on a malformed/
 * foreign URL, only decline to re-sign it.
 */
export function parseSignedUrl(url: string): ParsedSignedUrl | null {
  const configuredOrigin = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!configuredOrigin) return null;

  let parsedUrl: URL;
  let expectedOrigin: string;
  try {
    parsedUrl = new URL(url);
    expectedOrigin = new URL(configuredOrigin).origin;
  } catch {
    return null;
  }
  if (parsedUrl.origin !== expectedOrigin) return null;

  const match = SIGNED_URL_SHAPE.exec(parsedUrl.pathname);
  if (!match) return null;
  const [, bucket, encodedPath] = match;
  try {
    return { bucket, path: decodeURIComponent(encodedPath) };
  } catch {
    return null;
  }
}

interface SignedUrlResponse {
  signed_url: string;
  expires_in: number;
}

/**
 * Re-signs one expired media asset via the real GET /api/media/signed-url
 * endpoint (apps/api/app/modules/media/router.py). Returns null (never
 * throws) on a malformed input URL, a network failure, or a non-2xx
 * response -- callers fall back to their existing degrade path (AC2/AC3,
 * Story 2-45) rather than propagating an error.
 */
export async function refreshSignedUrl(expiredUrl: string): Promise<string | null> {
  const parsed = parseSignedUrl(expiredUrl);
  if (!parsed) return null;

  try {
    const { data } = await api.get<SignedUrlResponse>('media/signed-url', {
      params: { bucket: parsed.bucket, path: parsed.path, expires_in: RESIGN_EXPIRY_S },
    });
    return data.signed_url || null;
  } catch {
    return null;
  }
}
