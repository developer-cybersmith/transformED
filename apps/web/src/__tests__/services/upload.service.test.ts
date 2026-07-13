import { describe, it, expect, vi, beforeEach } from 'vitest';

const { postMock, getMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { post: postMock, get: getMock },
}));

import { uploadService, MAX_UPLOAD_SIZE_BYTES } from '@/services/upload.service';

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
    expect(config?.headers?.['Content-Type']).toBe('multipart/form-data');
    expect(data).toEqual(responseData);
  });

  it('propagates rejection (e.g. 413/422) instead of swallowing it', async () => {
    const error = { response: { status: 413, data: { detail: 'File exceeds 50 MB limit' } } };
    postMock.mockRejectedValue(error);

    const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
    await expect(uploadService.uploadLesson(file)).rejects.toBe(error);
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

describe('MAX_UPLOAD_SIZE_BYTES', () => {
  it('is 50MB, matching the backend limit', () => {
    expect(MAX_UPLOAD_SIZE_BYTES).toBe(50 * 1024 * 1024);
  });
});
