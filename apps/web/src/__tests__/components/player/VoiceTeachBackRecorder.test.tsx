// # MOCK-CONTRACT: real microphone access and real MediaRecorder encoding
// cannot run under jsdom/vitest -- navigator.mediaDevices.getUserMedia and
// the global MediaRecorder are necessarily mocked at the module level
// throughout this file, mirroring useAttentionMonitor.test.ts's existing
// getUserMedia-mocking convention for the same reason. Assertions target
// observable outcomes (rendered state, the Blob handed to onSubmit, mic
// track release) wherever the mocked boundary allows it, per binding rule 2.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  VoiceTeachBackRecorder,
  isVoiceRecordingSupported,
} from '@/components/player/VoiceTeachBackRecorder';

class FakeMediaRecorder {
  static isTypeSupported = vi.fn().mockReturnValue(true);
  state: 'inactive' | 'recording' = 'inactive';
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(
    public stream: MediaStream,
    options?: { mimeType?: string }
  ) {
    this.mimeType = options?.mimeType ?? '';
  }

  start() {
    this.state = 'recording';
  }

  stop() {
    if (this.state !== 'recording') return;
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['fake-audio-data'], { type: this.mimeType || 'audio/webm' }) });
    this.onstop?.();
  }
}

let fakeTrack: { stop: ReturnType<typeof vi.fn> };
let getUserMediaMock: ReturnType<typeof vi.fn>;
let createObjectURLMock: ReturnType<typeof vi.fn>;
let revokeObjectURLMock: ReturnType<typeof vi.fn>;

// jsdom implements no createObjectURL/revokeObjectURL at all -- assigned
// directly onto the real URL constructor (not a wholesale vi.stubGlobal
// replacement, which raced against @testing-library/react's own afterEach
// cleanup unmounting a still-mounted component after the stub was already
// torn down). Deliberately never restored -- there is no real jsdom
// implementation to restore to, and this file's own beforeEach reassigns a
// fresh mock before every test regardless (same "don't bother restoring an
// unimplemented jsdom API" precedent as useAttentionMonitor.test.ts's
// navigator.mediaDevices stub, which is likewise never restored).
function mockMediaSupport() {
  fakeTrack = { stop: vi.fn() };
  getUserMediaMock = vi.fn().mockResolvedValue({ getTracks: () => [fakeTrack] });
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia: getUserMediaMock },
    writable: true,
    configurable: true,
  });
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder);

  createObjectURLMock = vi.fn().mockReturnValue('blob:fake-url');
  revokeObjectURLMock = vi.fn();
  URL.createObjectURL = createObjectURLMock;
  URL.revokeObjectURL = revokeObjectURLMock;
}

beforeEach(() => {
  mockMediaSupport();
  FakeMediaRecorder.isTypeSupported.mockReset().mockReturnValue(true);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ── isVoiceRecordingSupported ────────────────────────────────────────────────

describe('isVoiceRecordingSupported', () => {
  it('returns true when getUserMedia and MediaRecorder both exist', () => {
    expect(isVoiceRecordingSupported()).toBe(true);
  });

  it('returns false when MediaRecorder is undefined', () => {
    vi.stubGlobal('MediaRecorder', undefined);
    expect(isVoiceRecordingSupported()).toBe(false);
  });

  it('returns false when navigator.mediaDevices is missing', () => {
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined, writable: true, configurable: true });
    expect(isVoiceRecordingSupported()).toBe(false);
  });
});

// ── VoiceTeachBackRecorder ───────────────────────────────────────────────────

describe('VoiceTeachBackRecorder', () => {
  it('starts in idle state with a Start Recording button', () => {
    render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.getByRole('button', { name: /start recording/i })).not.toBeNull();
  });

  it('requests the microphone and enters recording state on Start', async () => {
    render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);

    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));

    await waitFor(() => expect(getUserMediaMock).toHaveBeenCalledWith({ audio: true }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
  });

  it('has no timer element of any kind while recording (CLAUDE.md: no teach-back timer)', async () => {
    const { container } = render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());

    expect(container.textContent).not.toMatch(/\d+:\d{2}/);
    expect(screen.queryByRole('timer')).toBeNull();
  });

  it('shows an audio preview and Submit/Re-record actions after stopping', async () => {
    render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));

    await waitFor(() => expect(container_audio()).not.toBeNull());
    expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull();
    expect(screen.getByRole('button', { name: /re-record/i })).not.toBeNull();

    function container_audio() {
      return document.querySelector('audio');
    }
  });

  it('releases the mic track as soon as recording stops', async () => {
    render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));

    await waitFor(() => expect(fakeTrack.stop).toHaveBeenCalled());
  });

  it('calls onSubmit with the recorded blob and mime type when Submit Recording is clicked', async () => {
    const onSubmit = vi.fn();
    render(<VoiceTeachBackRecorder onSubmit={onSubmit} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [blob, mimeType] = onSubmit.mock.calls[0];
    expect(blob).toBeInstanceOf(Blob);
    expect(typeof mimeType).toBe('string');
  });

  it('returns to idle and discards the preview when Re-record is clicked', async () => {
    render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /re-record/i })).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /re-record/i }));

    expect(screen.getByRole('button', { name: /start recording/i })).not.toBeNull();
    expect(screen.queryByRole('button', { name: /submit recording/i })).toBeNull();
  });

  it('shows a graceful inline message, never a dead end, when mic permission is denied', async () => {
    getUserMediaMock.mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'));
    render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);

    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));

    await waitFor(() => expect(screen.getByText(/microphone/i)).not.toBeNull());
    // Never dead-ends: the Start Recording action remains available to retry.
    expect(screen.getByRole('button', { name: /start recording/i })).not.toBeNull();
  });

  it('disables Submit Recording and shows a scoring label while isSubmitting', async () => {
    const { rerender } = render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());

    rerender(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting />);

    const submitButton = screen.getByRole('button', { name: /scoring/i }) as HTMLButtonElement;
    expect(submitButton.disabled).toBe(true);
  });

  it('prefers audio/webm;codecs=opus when supported', async () => {
    FakeMediaRecorder.isTypeSupported.mockImplementation((type: string) => type === 'audio/webm;codecs=opus');
    const onSubmit = vi.fn();
    render(<VoiceTeachBackRecorder onSubmit={onSubmit} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));

    const [, mimeType] = onSubmit.mock.calls[0];
    expect(mimeType).toBe('audio/webm;codecs=opus');
  });

  it('falls through to the browser default when no preferred mime type is supported', async () => {
    FakeMediaRecorder.isTypeSupported.mockReturnValue(false);
    const onSubmit = vi.fn();
    render(<VoiceTeachBackRecorder onSubmit={onSubmit} isSubmitting={false} />);
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());

    // Should not throw and should still reach a submittable recorded state.
    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('auto-stops and shows a one-time notice after the max recording duration, never a live countdown', async () => {
    // userEvent's own internal scheduling depends on real timers even with
    // delay:null, which deadlocks under vi.useFakeTimers() -- fireEvent
    // dispatches synchronously with no such dependency, so the click itself
    // is a plain fireEvent here; only the recorder's own MAX_RECORDING_MS
    // setTimeout needs the fake clock advanced.
    vi.useFakeTimers();
    try {
      render(<VoiceTeachBackRecorder onSubmit={vi.fn()} isSubmitting={false} />);

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /start recording/i }));
        // Flush the microtask queue so getUserMedia's resolved promise and
        // the resulting setState('recording') land before timers advance.
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5 * 60 * 1000 + 1);
      });

      expect(screen.getByText(/automatically/i)).not.toBeNull();
      expect(screen.queryByRole('timer')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
