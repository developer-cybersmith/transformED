import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UploadFlow } from '@/components/dashboard/upload/UploadFlow';

const { pushMock, uploadLessonMock, getLessonStatusMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  uploadLessonMock: vi.fn(),
  getLessonStatusMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/services/upload.service', () => ({
  uploadService: {
    uploadLesson: uploadLessonMock,
    getLessonStatus: getLessonStatusMock,
  },
  extractErrorMessage: (err: unknown, fallback: string) => {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    return typeof detail === 'string' ? detail : fallback;
  },
  MAX_UPLOAD_SIZE_BYTES: 50 * 1024 * 1024,
}));

function dropAFile() {
  const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

function dropAnOversizedFile() {
  const file = new File(['%PDF-1.4'], 'huge.pdf', { type: 'application/pdf' });
  Object.defineProperty(file, 'size', { value: 51 * 1024 * 1024 });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

async function selectTier(user: ReturnType<typeof userEvent.setup>, label: 'Deep' | 'Balanced' | 'Refresher' = 'Deep') {
  const button = (await screen.findByText(label)).closest('button');
  await user.click(button!);
}

/** Drops a valid file and immediately picks a tier — the pre-upload flow shared by every test that exercises the actual upload/polling behavior. */
async function dropFileAndSelectTier(user: ReturnType<typeof userEvent.setup>, label: 'Deep' | 'Balanced' | 'Refresher' = 'Deep') {
  dropAFile();
  await selectTier(user, label);
}

beforeEach(() => {
  pushMock.mockReset();
  uploadLessonMock.mockReset();
  getLessonStatusMock.mockReset();
});

const READY_STATUS = { lesson_id: 'lsn_42', status: 'ready' as const, title: null, error: null, created_at: null, completed_at: null };

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

  it('dropping a valid file shows the mode-selection screen (all 3 tiers) before any upload call fires', async () => {
    render(<UploadFlow />);

    dropAFile();

    await screen.findByText('Deep');
    expect(screen.getByText('Balanced')).not.toBeNull();
    expect(screen.getByText('Refresher')).not.toBeNull();
    expect(uploadLessonMock).not.toHaveBeenCalled();
  });

  it('"Choose a different file" from the mode-selection screen returns to idle without ever uploading', async () => {
    const user = userEvent.setup();
    render(<UploadFlow />);

    dropAFile();
    await screen.findByText('Deep');
    await user.click(screen.getByText('Choose a different file'));

    expect(screen.getByText('Drop your course material here')).not.toBeNull();
    expect(uploadLessonMock).not.toHaveBeenCalled();
  });

  it('"Choose a different file" clears the file input value, so re-picking the same file is possible', async () => {
    const user = userEvent.setup();
    render(<UploadFlow />);

    dropAFile();
    await screen.findByText('Deep');
    await user.click(screen.getByText('Choose a different file'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.value).toBe('');
  });

  it('"Choose a different file" fully resets so a fresh drop/tier-pick cycle starts clean', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue(READY_STATUS);

    render(<UploadFlow />);

    dropAFile();
    await screen.findByText('Deep');
    await user.click(screen.getByText('Choose a different file'));

    await dropFileAndSelectTier(user, 'Refresher');

    await waitFor(() => expect(uploadLessonMock).toHaveBeenCalledTimes(1));
    await screen.findByText('Begin Lesson');
  });

  it('uploads, polls, and on "ready" shows "Begin Lesson" which navigates to the new lesson', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue(READY_STATUS);

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    await waitFor(() => expect(uploadLessonMock).toHaveBeenCalledWith(expect.any(File), 'T1'));
    await screen.findByText('Begin Lesson');
    await user.click(screen.getByText('Begin Lesson'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/lsn_42');
  });

  it('sends the mapped backend tier for a non-default selection (S2-09)', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue(READY_STATUS);

    render(<UploadFlow />);
    await dropFileAndSelectTier(user, 'Refresher');

    await waitFor(() => expect(uploadLessonMock).toHaveBeenCalledWith(expect.any(File), 'T3'));
  });

  it('shows the selected tier\'s visible label on the processing screen (S2-09)', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue({ lesson_id: 'lsn_42', status: 'running', title: null, error: null, created_at: null, completed_at: null });

    render(<UploadFlow />);
    await dropFileAndSelectTier(user, 'Balanced');

    await screen.findByText('Balanced', { selector: '[data-testid="selected-tier-label"]' });
  });

  it('completed state: "Generate Another" resets back to the idle drop zone', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue(READY_STATUS);

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    await screen.findByText('Generate Another');
    await user.click(screen.getByText('Generate Another'));

    expect(screen.getByText('Drop your course material here')).not.toBeNull();
  });

  it('on a "failed" status, shows the backend error and "Try Again" resets to idle', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue({
      lesson_id: 'lsn_42',
      status: 'failed',
      title: null,
      error: 'Cost ceiling exceeded',
      created_at: null,
      completed_at: null,
    });

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    await screen.findByText('Try Again');
    expect(screen.getByText('Cost ceiling exceeded')).not.toBeNull();

    await user.click(screen.getByText('Try Again'));
    expect(screen.getByText('Drop your course material here')).not.toBeNull();
  });

  it('surfaces an error immediately when the upload POST itself is rejected', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockRejectedValue({ response: { data: { detail: 'Invalid PDF' } } });

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    await screen.findByText('Invalid PDF');
    expect(getLessonStatusMock).not.toHaveBeenCalled();
  });

  it('stays in "processing" (no percentage/stage text) when a poll returns a non-terminal status', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue({ lesson_id: 'lsn_42', status: 'running', title: null, error: null, created_at: null, completed_at: null });

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    await waitFor(() => expect(getLessonStatusMock).toHaveBeenCalledTimes(1));
    await screen.findByText('Processing...');
    expect(screen.queryByText('Begin Lesson')).toBeNull();
    expect(screen.queryByText('Generation Failed')).toBeNull();
  });

  it('fails fast on a 4xx poll error instead of retrying like a transient failure', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockRejectedValue({ response: { status: 404 } });

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    await screen.findByText(/lesson not found/i);
    expect(getLessonStatusMock).toHaveBeenCalledTimes(1);
  });

  it('tolerates transient poll failures but surfaces an error after 3 consecutive failures', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockRejectedValue(new Error('network blip'));

    render(<UploadFlow />);
    await dropFileAndSelectTier(user);

    // 3 failures at a real 5s poll interval — this test genuinely waits ~10s of
    // wall-clock time for the 2nd and 3rd poll; kept real (no fake timers) because
    // framer-motion's AnimatePresence transitions never resolve under a faked
    // requestAnimationFrame/setTimeout clock in this environment.
    await waitFor(() => expect(getLessonStatusMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('Generation Failed')).toBeNull();

    await waitFor(() => expect(getLessonStatusMock).toHaveBeenCalledTimes(3), { timeout: 15000 });
    await screen.findByText(/lost connection/i);
  }, 20000);
});
