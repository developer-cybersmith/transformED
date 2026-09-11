import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TeachBackModal } from '@/components/player/TeachBackModal';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

const { submitTeachBackMock, submitTeachBackAudioMock, captureMock } = vi.hoisted(() => ({
  submitTeachBackMock: vi.fn(),
  submitTeachBackAudioMock: vi.fn(),
  captureMock: vi.fn(),
}));

vi.mock('@/lib/assessment', () => ({
  submitTeachBack: submitTeachBackMock,
  submitTeachBackAudio: submitTeachBackAudioMock,
}));

vi.mock('posthog-js', () => ({
  default: { capture: captureMock },
}));

const RESULT = {
  session_id: 'sess_1',
  rubric_scores: { accuracy: 'Strong', completeness: 'Developing', clarity: 'Strong' },
  overall_score: 76,
  ces_contribution: 0.1,
  feedback: 'Nice explanation of the core idea!',
};

beforeEach(() => {
  submitTeachBackMock.mockReset();
  submitTeachBackMock.mockResolvedValue(RESULT);
  submitTeachBackAudioMock.mockReset();
  submitTeachBackAudioMock.mockResolvedValue(RESULT);
  captureMock.mockReset();
  // Default jsdom has neither navigator.mediaDevices nor a global
  // MediaRecorder, so isVoiceRecordingSupported() is false and every
  // pre-existing test below renders exactly as it did before Story 2-63 --
  // no toggle, typed view only. The dedicated "voice input" describe block
  // further down opts into media support per-test instead.
  usePlayerStore.getState().loadLesson(mockLessonPackage);
  // A real sessionId is the realistic default (mintSession has already
  // resolved by the time a student reaches teach-back in normal use) --
  // tests that specifically care about the empty-sessionId guard override this.
  usePlayerStore.setState({ status: 'TEACH_BACK', currentSegmentIndex: 0, sessionId: 'sess_42' });
});

function renderModal() {
  return render(<TeachBackModal prompt="Explain SQL injection in your own words." segmentTitle="What is SQL Injection?" />);
}

describe('TeachBackModal', () => {
  it('renders the prompt and segment title', () => {
    renderModal();
    expect(screen.getByText('Explain SQL injection in your own words.')).not.toBeNull();
    expect(screen.getByText('What is SQL Injection?')).not.toBeNull();
  });

  it('has no timer element of any kind', () => {
    const { container } = renderModal();
    expect(container.textContent).not.toMatch(/\d+:\d{2}/); // mm:ss style countdown
    expect(screen.queryByRole('timer')).toBeNull();
  });

  it('auto-focuses the textarea on open', () => {
    renderModal();
    expect(document.activeElement).toBe(screen.getByPlaceholderText('Type your explanation here…'));
  });

  it('disables submit until text is entered', async () => {
    renderModal();
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It breaks the query.');
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('labels the submit button "Submit & Continue"', () => {
    renderModal();
    expect(screen.getByRole('button', { name: 'Submit & Continue' })).not.toBeNull();
  });

  it('Skip calls exitTeachBack without submitting', async () => {
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.click(screen.getByText('Skip'));

    expect(exitTeachBack).toHaveBeenCalled();
    expect(submitTeachBackMock).not.toHaveBeenCalled();
    // Story 2-54: Skip is not a submission.
    expect(captureMock).not.toHaveBeenCalledWith('teachback_submitted', expect.anything());
  });

  it('submits the trimmed response text with session/lesson/segment ids', async () => {
    usePlayerStore.setState({ sessionId: 'sess_42' });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), '  It terminates the query early.  ');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() =>
      expect(submitTeachBackMock).toHaveBeenCalledWith({
        session_id: 'sess_42',
        lesson_id: mockLessonPackage.lesson_id,
        segment_id: mockLessonPackage.segments[0].segment_id,
        response_text: 'It terminates the query early.',
      })
    );
    // Story 2-54
    expect(captureMock).toHaveBeenCalledWith('teachback_submitted', {
      lesson_id: mockLessonPackage.lesson_id,
      segment_id: mockLessonPackage.segments[0].segment_id,
    });
  });

  it('shows an encouraging message after scoring — never a numeric score or rubric breakdown', async () => {
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() => expect(screen.getByText(RESULT.feedback)).not.toBeNull());

    // No numeric score/percentage anywhere in the result view
    expect(screen.queryByText(/\d+%/)).toBeNull();
    expect(screen.queryByText(String(RESULT.overall_score))).toBeNull();
    // No rubric dimension breakdown shown to the student
    expect(screen.queryByText(/accuracy/i)).toBeNull();
    expect(screen.queryByText(/completeness/i)).toBeNull();
    expect(screen.queryByText(/clarity/i)).toBeNull();
  });

  it('Continue after scoring calls exitTeachBack', async () => {
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));
    await waitFor(() => expect(screen.getByText(RESULT.feedback)).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(exitTeachBack).toHaveBeenCalled();
  });

  it('does not block the student when the API call fails — exits teach-back gracefully', async () => {
    submitTeachBackMock.mockRejectedValue(new Error('network error'));
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() => expect(exitTeachBack).toHaveBeenCalled());
    // Story 2-54: a failed submission is not a successful one.
    expect(captureMock).not.toHaveBeenCalledWith('teachback_submitted', expect.anything());
  });

  it('does not call the API and exits gracefully when sessionId is still empty (mintSession has not resolved yet)', async () => {
    // Bug fix: session_id='' reaches Postgres as a real 500 (22P02 invalid
    // input syntax for type uuid) if this call is ever attempted.
    usePlayerStore.setState({ sessionId: '' });
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));

    await waitFor(() => expect(exitTeachBack).toHaveBeenCalled());
    expect(submitTeachBackMock).not.toHaveBeenCalled();
  });
});

describe('TeachBackModal — Story 2-55 accessibility (WCAG AA)', () => {
  it('has visible focus-ring classes on Skip, Submit & Continue, and the textarea', () => {
    renderModal();

    expect(screen.getByText('Skip').className).toMatch(/focus-visible:ring-4/);
    expect(screen.getByRole('button', { name: 'Submit & Continue' }).className).toMatch(/focus-visible:ring-4/);
    expect(screen.getByPlaceholderText('Type your explanation here…').className).toMatch(/focus:ring-4/);
  });

  it('has a visible focus-ring class on the result view Continue button', async () => {
    renderModal();

    await userEvent.type(screen.getByPlaceholderText('Type your explanation here…'), 'It terminates the query early.');
    await userEvent.click(screen.getByRole('button', { name: 'Submit & Continue' }));
    await waitFor(() => expect(screen.getByText(RESULT.feedback)).not.toBeNull());

    expect(screen.getByRole('button', { name: 'Continue' }).className).toMatch(/focus-visible:ring-4/);
  });
});

// # MOCK-CONTRACT: real microphone access and MediaRecorder encoding cannot
// run under jsdom/vitest -- see VoiceTeachBackRecorder.test.tsx for the same
// boundary and its own detailed rationale. This block only tests the
// toggle/wiring in TeachBackModal itself; the recorder's own internal state
// machine (permission denial, mime-type preference, auto-stop, etc.) is
// fully covered there and not re-tested here.
describe('TeachBackModal — Story 2-63 / BR-6 voice input', () => {
  class FakeMediaRecorder {
    static isTypeSupported = vi.fn().mockReturnValue(true);
    state: 'inactive' | 'recording' = 'inactive';
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    constructor(public stream: MediaStream) {}
    start() {
      this.state = 'recording';
    }
    stop() {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob(['fake-audio'], { type: 'audio/webm' }) });
      this.onstop?.();
    }
  }

  beforeEach(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
      writable: true,
      configurable: true,
    });
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    URL.createObjectURL = vi.fn().mockReturnValue('blob:fake-url');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the Type/Record toggle only when the browser supports voice recording', () => {
    renderModal();
    expect(screen.getByRole('tab', { name: 'Type' })).not.toBeNull();
    expect(screen.getByRole('tab', { name: 'Record' })).not.toBeNull();
  });

  it('defaults to the Type tab -- textarea visible, recorder not mounted', () => {
    renderModal();
    expect(screen.getByPlaceholderText('Type your explanation here…')).not.toBeNull();
    expect(screen.queryByRole('button', { name: /start recording/i })).toBeNull();
  });

  it('switches to the recorder and hides the typed Submit button when Record is selected', async () => {
    renderModal();
    await userEvent.click(screen.getByRole('tab', { name: 'Record' }));

    expect(screen.queryByPlaceholderText('Type your explanation here…')).toBeNull();
    expect(screen.getByRole('button', { name: /start recording/i })).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'Submit & Continue' })).toBeNull();
  });

  it('submits a voice recording via submitTeachBackAudio with the real session/segment ids', async () => {
    usePlayerStore.setState({ sessionId: 'sess_42' });
    renderModal();
    await userEvent.click(screen.getByRole('tab', { name: 'Record' }));
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));

    await waitFor(() =>
      expect(submitTeachBackAudioMock).toHaveBeenCalledWith(
        expect.objectContaining({
          session_id: 'sess_42',
          segment_id: mockLessonPackage.segments[0].segment_id,
        })
      )
    );
  });

  it('shows the same result view after a voice submission as after a typed one', async () => {
    renderModal();
    await userEvent.click(screen.getByRole('tab', { name: 'Record' }));
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));

    await waitFor(() => expect(screen.getByText(RESULT.feedback)).not.toBeNull());
    expect(screen.getByRole('button', { name: 'Continue' })).not.toBeNull();
  });

  it('fires teachback_submitted with source: "voice" -- the typed path\'s own capture call is untouched', async () => {
    renderModal();
    await userEvent.click(screen.getByRole('tab', { name: 'Record' }));
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));

    await waitFor(() =>
      expect(captureMock).toHaveBeenCalledWith('teachback_submitted', {
        lesson_id: mockLessonPackage.lesson_id,
        segment_id: mockLessonPackage.segments[0].segment_id,
        source: 'voice',
      })
    );
  });

  it('does not block the student when the audio submission fails -- exits teach-back gracefully', async () => {
    submitTeachBackAudioMock.mockRejectedValue(new Error('network error'));
    const exitTeachBack = vi.fn();
    usePlayerStore.setState({ exitTeachBack });
    renderModal();
    await userEvent.click(screen.getByRole('tab', { name: 'Record' }));
    await userEvent.click(screen.getByRole('button', { name: /start recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /stop recording/i })).not.toBeNull());
    await userEvent.click(screen.getByRole('button', { name: /stop recording/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /submit recording/i })).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /submit recording/i }));

    await waitFor(() => expect(exitTeachBack).toHaveBeenCalled());
  });
});
