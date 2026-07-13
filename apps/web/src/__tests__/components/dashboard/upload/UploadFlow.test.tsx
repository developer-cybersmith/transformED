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

  it('uploads, polls, and on "ready" shows "Begin Lesson" which navigates to the new lesson', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue(READY_STATUS);

    render(<UploadFlow />);
    dropAFile();

    await waitFor(() => expect(uploadLessonMock).toHaveBeenCalledWith(expect.any(File)));
    await screen.findByText('Begin Lesson');
    await user.click(screen.getByText('Begin Lesson'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/lsn_42');
  });

  it('completed state: "Generate Another" resets back to the idle drop zone', async () => {
    const user = userEvent.setup();
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockResolvedValue(READY_STATUS);

    render(<UploadFlow />);
    dropAFile();

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
    dropAFile();

    await screen.findByText('Try Again');
    expect(screen.getByText('Cost ceiling exceeded')).not.toBeNull();

    await user.click(screen.getByText('Try Again'));
    expect(screen.getByText('Drop your course material here')).not.toBeNull();
  });

  it('surfaces an error immediately when the upload POST itself is rejected', async () => {
    uploadLessonMock.mockRejectedValue({ response: { data: { detail: 'Invalid PDF' } } });

    render(<UploadFlow />);
    dropAFile();

    await screen.findByText('Invalid PDF');
    expect(getLessonStatusMock).not.toHaveBeenCalled();
  });

  it('tolerates transient poll failures but surfaces an error after 3 consecutive failures', async () => {
    uploadLessonMock.mockResolvedValue({ lesson_id: 'lsn_42', job_id: 'job_1', status: 'queued' });
    getLessonStatusMock.mockRejectedValue(new Error('network blip'));

    render(<UploadFlow />);
    dropAFile();

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
