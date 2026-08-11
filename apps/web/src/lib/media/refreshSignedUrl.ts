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

export interface ParsedSignedUrl {
  bucket: string;
  path: string;
}

/**
 * Extracts {bucket, path} from a Supabase signed URL. Returns null for any
 * URL that doesn't match the expected shape, or whose path segment is not
 * valid percent-encoding -- callers must never throw on a malformed/foreign
 * URL, only decline to re-sign it.
 */
export function parseSignedUrl(url: string): ParsedSignedUrl | null {
  const match = SIGNED_URL_SHAPE.exec(url);
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
      params: { bucket: parsed.bucket, path: parsed.path },
    });
    return data.signed_url ?? null;
  } catch {
    return null;
  }
}
