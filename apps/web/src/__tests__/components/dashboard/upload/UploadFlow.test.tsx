import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UploadFlow } from '@/components/dashboard/upload/UploadFlow';

const { pushMock, uploadLessonMock, getBookStatusMock, getLessonStatusMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  uploadLessonMock: vi.fn(),
  getBookStatusMock: vi.fn(),
  getLessonStatusMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Only `uploadService` is replaced. `extractErrorMessage` and
// `MAX_UPLOAD_SIZE_BYTES` come from the REAL module via importOriginal — the
// previous hand-written `extractErrorMessage` stub here could not disconfirm
// anything about the real one, and in fact diverged from it (it handled only a
// string `detail`, so it silently agreed with the very bug AC6 fixes).
vi.mock('@/services/upload.service', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/upload.service')>();
  return {
    ...actual,
    uploadService: {
      uploadLesson: uploadLessonMock,
      getBookStatus: getBookStatusMock,
      getLessonStatus: getLessonStatusMock,
    },
  };
});

function dropAFile() {
  const file = new File(['%PDF-1.4'], 'd2l.pdf', { type: 'application/pdf' });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

function dropAnOversizedFile() {
  const file = new File(['%PDF-1.4'], 'huge.pdf', { type: 'application/pdf' });
  Object.defineProperty(file, 'size', { value: 51 * 1024 * 1024 });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  pushMock.mockReset();
  uploadLessonMock.mockReset();
  getBookStatusMock.mockReset();
  getLessonStatusMock.mockReset();
});

// Story W0 AC5. The old fixture here was
// `{ lesson_id: 'lsn_42', status: 'ready', title, error, created_at, completed_at }`
// — a LESSON-shaped poll response the endpoint this flow polls can no longer
// produce. The upload flow polls GET /content/books/{id}, whose vocabulary is
// processing | ready | failed and which carries page_count/chapter_count.
// Values are the real 2026-08-04 capture (docs/contracts/book-api.v1.json).
const BOOK_ID = 'dfea46ac-1c6e-401a-a936-269eedd3e5d9';
const UPLOAD_ACCEPTED = { book_id: BOOK_ID, job_id: 'job_1', status: 'queued' };
const READY_BOOK = {
  book_id: BOOK_ID,
  filename: 'd2l.pdf',
  status: 'ready' as const,
  page_count: 1151,
  chapter_count: 21,
  created_at: '2026-08-04T10:55:09.608627+00:00',
};
const PROCESSING_BOOK = {
  book_id: BOOK_ID,
  filename: 'd2l.pdf',
  status: 'processing' as const,
  page_count: null,
  chapter_count: 0,
  created_at: '2026-08-04T10:58:58.435893+00:00',
};

describe('UploadFlow', () => {
  it('renders the idle drop zone with a real, keyboard-focusable "Browse Files" button', () => {
    render(<UploadFlow />);

    const button = screen.getByText('Browse Files').closest('button');
    expect(button).not.toBeNull();
  });

  it('rejects an oversized file client-side without calling the upload API', async () => {
    render(<UploadFlow />);

    dropAnOversizedFile();

    await screen.findByText(/exceeds the 50MB limit/i);
    expect(uploadLessonMock).not.toHaveBeenCalled();
  });

  // ── AC5: INVERTED, not deleted ────────────────────────────────────────────
  // Was `expect(uploadLessonMock).toHaveBeenCalledWith(expect.any(File), 'T1')`
  // via a tier-selection screen. A book has no tier: sending one is a 422, and
  // the tier is now chosen per chapter at generation time. The assertion is
  // kept and pointed the other way — the call must carry the file ALONE.
  it('uploads with the file alone — no tier argument, ever (AC5)', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(READY_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await waitFor(() => expect(uploadLessonMock).toHaveBeenCalledTimes(1));
    expect(uploadLessonMock.mock.calls[0]).toHaveLength(1);
    expect(uploadLessonMock.mock.calls[0][0]).toBeInstanceOf(File);
  });

  it('goes straight from a valid drop to processing — there is no tier screen to pass through (AC5)', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(PROCESSING_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('Finding the chapters...');
    expect(screen.queryByText('Deep')).toBeNull();
    expect(screen.queryByText('Balanced')).toBeNull();
    expect(screen.queryByText('Refresher')).toBeNull();
  });

  it('polls the BOOK endpoint, not the lesson endpoint (AC5)', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(READY_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await waitFor(() => expect(getBookStatusMock).toHaveBeenCalledWith(BOOK_ID));
    expect(getLessonStatusMock).not.toHaveBeenCalled();
  });

  it('on "ready" shows the chapter count and navigates to the BOOK page, not a lesson page', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(READY_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('21 chapters ready');
    await user.click(screen.getByText('Choose a chapter'));

    expect(pushMock).toHaveBeenCalledWith(`/books/${BOOK_ID}`);
  });

  it('reports real ingestion progress from chapter_count rather than a fabricated percentage', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue({ ...PROCESSING_BOOK, page_count: 1151, chapter_count: 7 });

    render(<UploadFlow />);
    dropAFile();

    const badge = await screen.findByTestId('chapter-count-progress');
    expect(badge.textContent).toContain('7 chapters so far');
    expect(screen.getByText(/Reading 1,151 pages/)).not.toBeNull();
  });

  it('shows no chapter-count badge while the book has detected nothing yet', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(PROCESSING_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await waitFor(() => expect(getBookStatusMock).toHaveBeenCalledTimes(1));
    await screen.findByText('Finding the chapters...');
    expect(screen.queryByTestId('chapter-count-progress')).toBeNull();
  });

  it('completed state: "Upload another book" resets back to the idle drop zone', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(READY_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('Upload another book');
    await user.click(screen.getByText('Upload another book'));

    expect(screen.getByText('Drop your textbook here')).not.toBeNull();
  });

  it('resets the file input value so re-picking the SAME file still fires a change event', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(READY_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('Upload another book');
    await user.click(screen.getByText('Upload another book'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.value).toBe('');
  });

  it('on a "failed" book, explains the PDF could not be read and "Try Again" resets to idle', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue({ ...PROCESSING_BOOK, status: 'failed' as const });

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('Try Again');
    expect(screen.getByText(/couldn't read this PDF/i)).not.toBeNull();

    await user.click(screen.getByText('Try Again'));
    expect(screen.getByText('Drop your textbook here')).not.toBeNull();
  });

  it('surfaces an error immediately when the upload POST itself is rejected', async () => {
    uploadLessonMock.mockRejectedValue({ response: { data: { detail: 'File is not a valid PDF' } } });

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('File is not a valid PDF');
    expect(getBookStatusMock).not.toHaveBeenCalled();
  });

  it('surfaces the real 422 the endpoint returns when a tier is sent (AC5/AC6)', async () => {
    uploadLessonMock.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail:
            'tier is no longer accepted on upload — a book has no tier. Choose it per chapter ' +
            'when generating a lesson (POST /books/{book_id}/chapters/{chapter_id}/lessons).',
        },
      },
    });

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText(/a book has no tier/i);
  });

  it('stays in "processing" when a poll returns a non-terminal status', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockResolvedValue(PROCESSING_BOOK);

    render(<UploadFlow />);
    dropAFile();

    await waitFor(() => expect(getBookStatusMock).toHaveBeenCalledTimes(1));
    await screen.findByText('Finding the chapters...');
    expect(screen.queryByText('Choose a chapter')).toBeNull();
    expect(screen.queryByText('Upload Failed')).toBeNull();
  });

  it('fails fast on a 4xx poll error instead of retrying like a transient failure', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockRejectedValue({ response: { status: 404 } });

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText(/book not found/i);
    expect(getBookStatusMock).toHaveBeenCalledTimes(1);
  });

  it('tolerates transient poll failures but surfaces an error after 3 consecutive failures', async () => {
    uploadLessonMock.mockResolvedValue(UPLOAD_ACCEPTED);
    getBookStatusMock.mockRejectedValue(new Error('network blip'));

    render(<UploadFlow />);
    dropAFile();

    // 3 failures at the real 8s poll interval (LESSON_STATUS_POLL_INTERVAL_MS)
    // — this test genuinely waits ~16s of wall-clock time for the 2nd and 3rd
    // poll. Kept real (NO fake timers) because framer-motion's AnimatePresence
    // transitions never resolve under a faked requestAnimationFrame/setTimeout
    // clock in this environment. Do not "optimise" this into fake timers.
    await waitFor(() => expect(getBookStatusMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('Upload Failed')).toBeNull();

    await waitFor(() => expect(getBookStatusMock).toHaveBeenCalledTimes(3), { timeout: 25000 });
    await screen.findByText(/lost connection/i);
  }, 30000);
});
