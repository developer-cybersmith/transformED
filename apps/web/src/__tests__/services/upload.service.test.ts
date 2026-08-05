import { describe, it, expect, vi, beforeEach, expectTypeOf } from 'vitest';

const { postMock, getMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
}));

// Module-level mock, NOT MSW: these tests assert the exact call SHAPE the
// service produces (url, FormData contents, absence of a header). The
// network-level contract — that this shape is the one the API accepts — is
// covered by `src/test/contract.test.ts` against MSW. Never both for one test.
vi.mock('@/lib/api', () => ({
  api: { post: postMock, get: getMock },
}));

import { uploadService, extractErrorMessage } from '@/services/upload.service';

beforeEach(() => {
  postMock.mockReset();
  getMock.mockReset();
});

// Story W0 AC5. This fixture used to be
// `{ lesson_id: 'lsn_1', job_id: 'job_1', status: 'queued' }` — a shape the
// endpoint can no longer produce. POST content/lessons ingests a BOOK; there is
// no lesson to name yet, and the test asserting otherwise passed happily while
// every real upload 422'd.
const UPLOAD_RESPONSE = { book_id: 'bok_1', job_id: 'job_1', status: 'queued' };

describe('uploadService.uploadLesson', () => {
  it('POSTs multipart form data to content/lessons and returns response.data', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    postMock.mockResolvedValue({ data: UPLOAD_RESPONSE });

    const data = await uploadService.uploadLesson(file);

    expect(postMock).toHaveBeenCalledTimes(1);
    const [url, body, config] = postMock.mock.calls[0];
    expect(url).toBe('content/lessons');
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('file')).toBe(file);
    // No explicit Content-Type — axios/the browser must generate the multipart
    // boundary itself; forcing the header here would strip it.
    expect(config?.headers?.['Content-Type']).toBeUndefined();
    expect(data).toEqual(UPLOAD_RESPONSE);
  });

  it('returns a book_id and no lesson_id — an upload creates a book, not a lesson (AC5)', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    postMock.mockResolvedValue({ data: UPLOAD_RESPONSE });

    const data = await uploadService.uploadLesson(file);

    expect(data.book_id).toBe('bok_1');
    expect(data).not.toHaveProperty('lesson_id');
  });

  it('propagates rejection (e.g. 413/422) instead of swallowing it', async () => {
    const error = { response: { status: 413, data: { detail: 'File exceeds 50 MB limit' } } };
    postMock.mockRejectedValue(error);

    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    await expect(uploadService.uploadLesson(file)).rejects.toBe(error);
  });

  // ── AC5: INVERTED, not deleted ────────────────────────────────────────────
  // Was `expect(body.get('tier')).toBe('T3')`. The backend now 422s on the mere
  // presence of `tier` ("a book has no tier"), so the old assertion described a
  // request that fails 100 % of the time — and passed. The inversion below is
  // the same assertion pointed the other way, and it is the one that must hold
  // forever: a book is not a thing that has a difficulty tier.
  it('NEVER sends tier — the field 422s the upload endpoint outright (AC5)', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    postMock.mockResolvedValue({ data: UPLOAD_RESPONSE });

    await uploadService.uploadLesson(file);

    const [, body] = postMock.mock.calls[0];
    expect(body.has('tier')).toBe(false);
    expect([...(body as FormData).keys()]).toEqual(['file']);
  });

  it('still sends no tier when a stale caller passes one anyway (AC5)', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    postMock.mockResolvedValue({ data: UPLOAD_RESPONSE });

    // Bypasses the compile-time arity check on purpose — simulates a caller that
    // was not updated (or an `as any`). The extra argument must be ignored, not
    // forwarded, because forwarding it is an instant 422.
    await (uploadService.uploadLesson as (f: File, t?: string) => Promise<unknown>)(file, 'T3');

    const [, body] = postMock.mock.calls[0];
    expect(body.has('tier')).toBe(false);
  });

  // ── AC5: the expectTypeOf tripwire is KEPT, inverted ──────────────────────
  // It used to pin parameter 1 to `'T1'|'T2'|'T3'|undefined`. Its job was always
  // to fail loudly the moment the tier parameter changes — that is why it is
  // worth keeping. It now pins the signature to exactly `[File]`, so re-adding a
  // tier parameter to a book upload fails at type-check rather than as a runtime
  // 422 in front of a user.
  it('takes a File and nothing else — re-adding a tier parameter must fail at compile time (AC5)', () => {
    expectTypeOf(uploadService.uploadLesson).parameters.toEqualTypeOf<[File]>();
  });
});

describe('uploadService.getBookStatus', () => {
  it('GETs content/books/{id} and returns response.data', async () => {
    const book = {
      book_id: 'bok_1',
      filename: 'd2l.pdf',
      status: 'processing' as const,
      page_count: null,
      chapter_count: 0,
      created_at: '2026-08-04T10:58:58.435893+00:00',
    };
    getMock.mockResolvedValue({ data: book });

    const data = await uploadService.getBookStatus('bok_1');

    expect(getMock).toHaveBeenCalledWith('content/books/bok_1');
    expect(data).toEqual(book);
  });

  it('propagates rejection instead of swallowing it', async () => {
    const error = { response: { status: 404 } };
    getMock.mockRejectedValue(error);

    await expect(uploadService.getBookStatus('missing')).rejects.toBe(error);
  });
});

describe('uploadService.getLessonStatus', () => {
  it('GETs content/lessons/{id} and returns response.data', async () => {
    const status = {
      lesson_id: 'lsn_1',
      status: 'running' as const,
      title: null,
      error: null,
      created_at: '2026-07-13T00:00:00Z',
      completed_at: null,
    };
    getMock.mockResolvedValue({ data: status });

    const data = await uploadService.getLessonStatus('lsn_1');

    expect(getMock).toHaveBeenCalledWith('content/lessons/lsn_1');
    expect(data).toEqual(status);
  });

  it('propagates rejection instead of swallowing it', async () => {
    const error = { response: { status: 404 } };
    getMock.mockRejectedValue(error);

    await expect(uploadService.getLessonStatus('missing')).rejects.toBe(error);
  });
});

describe('extractErrorMessage', () => {
  it('returns a string detail as-is', () => {
    const err = { response: { data: { detail: 'File is not a valid PDF' } } };
    expect(extractErrorMessage(err, 'fallback')).toBe('File is not a valid PDF');
  });

  it('extracts msg from FastAPI\'s array-shaped 422 validation detail', () => {
    const err = { response: { data: { detail: [{ loc: ['body', 'file'], msg: 'field required', type: 'value_error.missing' }] } } };
    expect(extractErrorMessage(err, 'fallback')).toBe('field required');
  });

  it('falls back when detail is missing or an empty array', () => {
    expect(extractErrorMessage({ response: { data: {} } }, 'fallback')).toBe('fallback');
    expect(extractErrorMessage({ response: { data: { detail: [] } } }, 'fallback')).toBe('fallback');
    expect(extractErrorMessage(new Error('network blip'), 'fallback')).toBe('fallback');
  });

  // ── AC6 ───────────────────────────────────────────────────────────────────
  it('renders the object-shaped chapter_too_large detail instead of dropping it', () => {
    const err = {
      response: {
        data: {
          detail: {
            code: 'chapter_too_large',
            page_span: 260,
            max_page_span: 200,
            boundary_confidence: 'toc',
          },
        },
      },
    };

    const message = extractErrorMessage(err, 'fallback');

    expect(message).not.toBe('fallback');
    expect(message).toContain('260');
    expect(message).toContain('200');
  });

  it('distinguishes failed boundary detection from a genuinely enormous chapter', () => {
    const err = {
      response: {
        data: {
          detail: {
            code: 'chapter_too_large',
            page_span: 1151,
            max_page_span: 200,
            boundary_confidence: 'fallback',
          },
        },
      },
    };

    const message = extractErrorMessage(err, 'fallback');

    expect(message).toContain('1,151');
    expect(message).toMatch(/couldn't find chapter boundaries/i);
  });

  it('falls back to the code for an object detail it does not recognise', () => {
    const err = { response: { data: { detail: { code: 'some_future_code' } } } };
    expect(extractErrorMessage(err, 'fallback')).toBe('some_future_code');
  });

  it('falls back when the object detail carries no usable code at all', () => {
    const err = { response: { data: { detail: { page_span: 300 } } } };
    expect(extractErrorMessage(err, 'fallback')).toBe('fallback');
  });
});
