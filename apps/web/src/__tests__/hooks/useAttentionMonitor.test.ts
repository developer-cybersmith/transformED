import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAttentionMonitor } from '@/hooks/useAttentionMonitor';
import { usePlayerStore } from '@/stores/player.machine';

const { useAttentionConsentMock, forVisionTasksMock, createFromOptionsMock, detectForVideoMock, closeMock } =
  vi.hoisted(() => ({
    useAttentionConsentMock: vi.fn(),
    forVisionTasksMock: vi.fn(),
    createFromOptionsMock: vi.fn(),
    detectForVideoMock: vi.fn(),
    closeMock: vi.fn(),
  }));

vi.mock('@/hooks/useAttentionConsent', () => ({
  useAttentionConsent: useAttentionConsentMock,
}));

vi.mock('@mediapipe/tasks-vision', () => ({
  FilesetResolver: { forVisionTasks: forVisionTasksMock },
  FaceLandmarker: { createFromOptions: createFromOptionsMock },
}));

const IDENTITY_MATRIX = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

function acceptedConsent() {
  return { consentStatus: 'accepted' as const, isLoading: false, showModal: false, accept: vi.fn(), decline: vi.fn() };
}

function unresolvedConsent() {
  return { consentStatus: 'unknown' as const, isLoading: true, showModal: false, accept: vi.fn(), decline: vi.fn() };
}

describe('useAttentionMonitor', () => {
  let fakeTrack: { stop: ReturnType<typeof vi.fn> };
  let getUserMediaMock: ReturnType<typeof vi.fn>;
  let sendMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();

    useAttentionConsentMock.mockReset().mockReturnValue(acceptedConsent());

    forVisionTasksMock.mockReset().mockResolvedValue({});
    detectForVideoMock.mockReset().mockReturnValue({
      faceBlendshapes: [{ categories: [] }],
      facialTransformationMatrixes: [{ data: IDENTITY_MATRIX }],
    });
    closeMock.mockReset();
    createFromOptionsMock.mockReset().mockResolvedValue({
      detectForVideo: detectForVideoMock,
      close: closeMock,
    });

    fakeTrack = { stop: vi.fn() };
    getUserMediaMock = vi.fn().mockResolvedValue({ getTracks: () => [fakeTrack] });
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: getUserMediaMock },
      writable: true,
      configurable: true,
    });
    HTMLVideoElement.prototype.play = vi.fn().mockResolvedValue(undefined);

    sendMock = vi.fn();
    usePlayerStore.setState({
      tutorState: 'IDLE',
      sessionId: 'sess_1',
      wsSendAttentionSignal: sendMock,
    });

    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function flush(ms = 0) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it('does not request the camera while consent is still loading (AC-2/AC-8)', async () => {
    useAttentionConsentMock.mockReturnValue(unresolvedConsent());
    renderHook(() => useAttentionMonitor());
    await flush();

    expect(getUserMediaMock).not.toHaveBeenCalled();
  });

  it('does not request the camera when consent is declined (AC-2/AC-8)', async () => {
    useAttentionConsentMock.mockReturnValue({
      consentStatus: 'declined',
      isLoading: false,
      showModal: false,
      accept: vi.fn(),
      decline: vi.fn(),
    });
    renderHook(() => useAttentionMonitor());
    await flush();

    expect(getUserMediaMock).not.toHaveBeenCalled();
  });

  it('requests the camera and initializes MediaPipe once consent resolves to accepted (AC-1/AC-2)', async () => {
    renderHook(() => useAttentionMonitor());
    await flush();

    expect(getUserMediaMock).toHaveBeenCalledWith({ video: true });
    expect(forVisionTasksMock).toHaveBeenCalled();
    expect(createFromOptionsMock).toHaveBeenCalled();
  });

  it('initializes only after consent transitions from loading to accepted, not before (AC-2/AC-8)', async () => {
    useAttentionConsentMock.mockReturnValue(unresolvedConsent());
    const { rerender } = renderHook(() => useAttentionMonitor());
    await flush();
    expect(getUserMediaMock).not.toHaveBeenCalled();

    useAttentionConsentMock.mockReturnValue(acceptedConsent());
    rerender();
    await flush();

    expect(getUserMediaMock).toHaveBeenCalledTimes(1);
  });

  it('sends exactly one AttentionSignalMessage per 5-second window while tutorState is TEACHING (AC-3)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    await flush(5000);

    expect(sendMock).toHaveBeenCalledTimes(1);
    const [msg] = sendMock.mock.calls[0];
    expect(msg).toEqual({
      type: 'attention_signal',
      payload: {
        session_id: 'sess_1',
        quiz_accuracy: null,
        teachback_score: null,
        behavioral_score: expect.any(Number),
        head_pose_score: expect.any(Number),
        blink_rate: expect.any(Number),
      },
    });
    expect(Object.keys(msg.payload)).toHaveLength(6);
  });

  it('sends no signal while tutorState is not TEACHING (AC-4)', async () => {
    usePlayerStore.setState({ tutorState: 'QUIZZING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    await flush(5000);

    expect(sendMock).not.toHaveBeenCalled();
  });

  it('resumes sending on the next window after returning to TEACHING, without re-initializing the camera/model (AC-4)', async () => {
    usePlayerStore.setState({ tutorState: 'QUIZZING' });
    renderHook(() => useAttentionMonitor());
    await flush();
    await flush(5000);
    expect(sendMock).not.toHaveBeenCalled();

    act(() => usePlayerStore.setState({ tutorState: 'TEACHING' }));
    await flush(5000);

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(getUserMediaMock).toHaveBeenCalledTimes(1);
    expect(createFromOptionsMock).toHaveBeenCalledTimes(1);
  });

  it('does not throw and sends nothing when wsSendAttentionSignal is null (socket disconnected)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING', wsSendAttentionSignal: null });
    renderHook(() => useAttentionMonitor());
    await flush();

    await expect(flush(5000)).resolves.not.toThrow();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('degrades gracefully and logs when MediaPipe fails to initialize, never throwing (AC-6)', async () => {
    createFromOptionsMock.mockRejectedValue(new Error('WASM load failed'));
    usePlayerStore.setState({ tutorState: 'TEACHING' });

    renderHook(() => useAttentionMonitor());
    await flush();
    await flush(5000);

    expect(console.error).toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('stops the camera and closes the model on unmount (AC-7)', async () => {
    const { unmount } = renderHook(() => useAttentionMonitor());
    await flush();

    unmount();

    expect(fakeTrack.stop).toHaveBeenCalledTimes(1);
    expect(closeMock).toHaveBeenCalledTimes(1);
  });

  it('stops the camera and closes the model once tutorState reaches SESSION_END, and stops sending further signals (AC-7)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    act(() => usePlayerStore.setState({ tutorState: 'SESSION_END' }));
    await flush(100); // one frame tick is enough to observe SESSION_END

    expect(fakeTrack.stop).toHaveBeenCalledTimes(1);
    expect(closeMock).toHaveBeenCalledTimes(1);

    sendMock.mockClear();
    await flush(5000);
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('does not tear down the camera/model on a pause outside TEACHING (AC-4 vs AC-7 distinction)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    act(() => usePlayerStore.setState({ tutorState: 'CHECKING_IN' }));
    await flush(5000);

    expect(fakeTrack.stop).not.toHaveBeenCalled();
    expect(closeMock).not.toHaveBeenCalled();
  });
});
