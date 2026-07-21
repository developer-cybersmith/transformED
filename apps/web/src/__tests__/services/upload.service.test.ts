import { describe, it, expect, vi, beforeEach } from 'vitest';

const { postMock, getMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { post: postMock, get: getMock },
}));

import { uploadService, extractErrorMessage } from '@/services/upload.service';

beforeEach(() => {
  postMock.mockReset();
  getMock.mockReset();
});

describe('uploadService.uploadLesson', () => {
  it('POSTs multipart form data to content/lessons and returns response.data', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    const responseData = { lesson_id: 'lsn_1', job_id: 'job_1', status: 'queued' };
    postMock.mockResolvedValue({ data: responseData });

    const data = await uploadService.uploadLesson(file);

    expect(postMock).toHaveBeenCalledTimes(1);
    const [url, body, config] = postMock.mock.calls[0];
    expect(url).toBe('content/lessons');
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('file')).toBe(file);
    // No explicit Content-Type — axios/the browser must generate the multipart
    // boundary itself; forcing the header here would strip it.
    expect(config?.headers?.['Content-Type']).toBeUndefined();
    expect(data).toEqual(responseData);
  });

  it('propagates rejection (e.g. 413/422) instead of swallowing it', async () => {
    const error = { response: { status: 413, data: { detail: 'File exceeds 50 MB limit' } } };
    postMock.mockRejectedValue(error);

    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    await expect(uploadService.uploadLesson(file)).rejects.toBe(error);
  });

  it('appends tier to FormData when provided (S2-09)', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    postMock.mockResolvedValue({ data: { lesson_id: 'lsn_1', job_id: 'job_1', status: 'queued' } });

    await uploadService.uploadLesson(file, 'T3');

    const [, body] = postMock.mock.calls[0];
    expect(body.get('tier')).toBe('T3');
  });

  it('omits the tier field entirely when not provided, relying on the backend default (S2-09)', async () => {
    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    postMock.mockResolvedValue({ data: { lesson_id: 'lsn_1', job_id: 'job_1', status: 'queued' } });

    await uploadService.uploadLesson(file);

    const [, body] = postMock.mock.calls[0];
    expect(body.has('tier')).toBe(false);
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
});
