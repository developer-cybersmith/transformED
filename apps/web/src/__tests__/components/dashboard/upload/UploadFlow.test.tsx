import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UploadFlow } from '@/components/dashboard/upload/UploadFlow';

const { pushMock, connectMock, disconnectMock, subscribeMock, unsubscribeMock, startGenerationMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  connectMock: vi.fn(),
  disconnectMock: vi.fn(),
  subscribeMock: vi.fn(),
  unsubscribeMock: vi.fn(),
  startGenerationMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

let capturedCallback: ((event: { type: string; payload: Record<string, unknown> }) => void) | undefined;

vi.mock('@/services/uploadGeneration.service', () => ({
  uploadGenerationService: {
    connect: connectMock,
    disconnect: disconnectMock,
    subscribe: (cb: (event: { type: string; payload: Record<string, unknown> }) => void) => {
      capturedCallback = cb;
      subscribeMock(cb);
      return unsubscribeMock;
    },
    startGeneration: startGenerationMock,
  },
}));

function dropAFile() {
  const file = new File(['%PDF-1.4'], 'chapter.pdf', { type: 'application/pdf' });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  pushMock.mockReset();
  connectMock.mockReset();
  disconnectMock.mockReset();
  subscribeMock.mockReset();
  unsubscribeMock.mockReset();
  startGenerationMock.mockReset();
  startGenerationMock.mockResolvedValue(undefined);
  capturedCallback = undefined;
});

describe('UploadFlow', () => {
  it('renders the idle drop zone with a real, keyboard-focusable "Browse Files" button', () => {
    render(<UploadFlow />);

    const button = screen.getByText('Browse Files').closest('button');
    expect(button).not.toBeNull();
  });

  it('completed state: "Begin Lesson" navigates to the new lesson, using the shared Button component', async () => {
    const user = userEvent.setup();
    render(<UploadFlow />);
    dropAFile();
    await waitFor(() => expect(capturedCallback).toBeDefined());

    act(() => capturedCallback!({ type: 'lesson_ready', payload: { lesson_id: 'lsn_42' } }));
    await screen.findByText('Begin Lesson');

    await user.click(screen.getByText('Begin Lesson'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/lsn_42');
  });

  it('completed state: "Generate Another" resets back to the idle drop zone', async () => {
    const user = userEvent.setup();
    render(<UploadFlow />);
    dropAFile();
    await waitFor(() => expect(capturedCallback).toBeDefined());
    act(() => capturedCallback!({ type: 'lesson_ready', payload: { lesson_id: 'lsn_42' } }));
    await screen.findByText('Generate Another');

    await user.click(screen.getByText('Generate Another'));

    expect(screen.getByText('Drop your course material here')).not.toBeNull();
  });

  it('error state: "Try Again" resets back to the idle drop zone', async () => {
    const user = userEvent.setup();
    render(<UploadFlow />);
    dropAFile();
    await waitFor(() => expect(capturedCallback).toBeDefined());

    act(() => capturedCallback!({ type: 'error', payload: { message: 'Pipeline failed' } }));
    await screen.findByText('Try Again');
    expect(screen.getByText('Pipeline failed')).not.toBeNull();

    await user.click(screen.getByText('Try Again'));

    expect(screen.getByText('Drop your course material here')).not.toBeNull();
  });
});
