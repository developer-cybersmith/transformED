// # MOCK-CONTRACT: real MediaPipe WASM and real camera access cannot run
// under jsdom/vitest -- @mediapipe/tasks-vision and navigator.mediaDevices
// are necessarily mocked at the module level throughout this file. See
// docs/stories/2-44-attention-monitor.md Dev Notes > Testing standards for
// why no real-dependency test is possible for this boundary. Assertions
// still target observable outcomes (the exact payload sent, teardown call
// counts) wherever the mocked boundary allows it, per binding rule 2.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAttentionMonitor } from '@/hooks/useAttentionMonitor';
import { usePlayerStore } from '@/stores/player.machine';
import { computeHeadPoseScore, computeGazeScore, computeBehavioralScore } from '@/lib/attention/signalMath';

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
// A mild, non-dead-center matrix (~10-degree yaw) and non-empty look-away
// blendshapes, so head_pose_score and the gaze component feeding
// behavioral_score are DISTINCT, known values -- unlike an identity matrix +
// empty blendshapes (both evaluate to 1), which cannot detect a bug that
// swapped which sample array feeds which output field (review finding).
const MILD_YAW_MATRIX = (() => {
  const rad = (10 * Math.PI) / 180;
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];
})();
const MILD_LOOK_AWAY_BLENDSHAPES = [{ categoryName: 'eyeLookOutLeft', score: 0.8 }];
const NO_FACE_RESULT = { faceBlendshapes: [], facialTransformationMatrixes: [] };

function faceDetectedResult(
  matrix: number[] = MILD_YAW_MATRIX,
  blendshapeCategories: { categoryName: string; score: number }[] = MILD_LOOK_AWAY_BLENDSHAPES,
) {
  return {
    faceBlendshapes: [{ categories: blendshapeCategories }],
    facialTransformationMatrixes: [{ data: matrix }],
  };
}

function acceptedConsent() {
  return { consentStatus: 'accepted' as const, isLoading: false, showModal: false, accept: vi.fn(), decline: vi.fn() };
}

function unresolvedConsent() {
  return { consentStatus: 'unknown' as const, isLoading: true, showModal: false, accept: vi.fn(), decline: vi.fn() };
}

describe('useAttentionMonitor', () => {
  let fakeTrack: { stop: ReturnType<typeof vi.fn>; onended: (() => void) | null };
  let getUserMediaMock: ReturnType<typeof vi.fn>;
  let sendMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();

    useAttentionConsentMock.mockReset().mockReturnValue(acceptedConsent());

    forVisionTasksMock.mockReset().mockResolvedValue({});
    detectForVideoMock.mockReset().mockReturnValue(faceDetectedResult());
    closeMock.mockReset();
    createFromOptionsMock.mockReset().mockResolvedValue({
      detectForVideo: detectForVideoMock,
      close: closeMock,
    });

    fakeTrack = { stop: vi.fn(), onended: null };
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
    vi.spyOn(console, 'warn').mockImplementation(() => {});
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
    usePlayerStore.setState({ tutorState: 'TEACHING' });
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
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    expect(getUserMediaMock).not.toHaveBeenCalled();
  });

  it('does not request the camera while tutorState has never reached TEACHING, even with consent already accepted (AC-1, review finding)', async () => {
    // tutorState stays at the beforeEach default of 'IDLE' -- a returning
    // student whose consent already resolved must not have their camera
    // activated before the lesson actually starts.
    renderHook(() => useAttentionMonitor());
    await flush();

    expect(getUserMediaMock).not.toHaveBeenCalled();
  });

  it('requests the camera and initializes MediaPipe once tutorState reaches TEACHING with consent already accepted (AC-1/AC-2)', async () => {
    const { rerender } = renderHook(() => useAttentionMonitor());
    await flush();
    expect(getUserMediaMock).not.toHaveBeenCalled();

    act(() => usePlayerStore.setState({ tutorState: 'TEACHING' }));
    rerender();
    await flush();

    expect(getUserMediaMock).toHaveBeenCalledWith({ video: true });
    expect(forVisionTasksMock).toHaveBeenCalled();
    expect(createFromOptionsMock).toHaveBeenCalled();
  });

  it('initializes only after consent transitions from loading to accepted, not before (AC-2/AC-8)', async () => {
    useAttentionConsentMock.mockReturnValue(unresolvedConsent());
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    const { rerender } = renderHook(() => useAttentionMonitor());
    await flush();
    expect(getUserMediaMock).not.toHaveBeenCalled();

    useAttentionConsentMock.mockReturnValue(acceptedConsent());
    rerender();
    await flush();

    expect(getUserMediaMock).toHaveBeenCalledTimes(1);
  });

  it('does not tear down or re-initialize once TEACHING has been reached, even if tutorState later leaves and returns (AC-4 vs AC-1 ordering)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();
    expect(getUserMediaMock).toHaveBeenCalledTimes(1);

    act(() => usePlayerStore.setState({ tutorState: 'CHECKING_IN' }));
    await flush(100);
    act(() => usePlayerStore.setState({ tutorState: 'TEACHING' }));
    await flush(100);

    expect(getUserMediaMock).toHaveBeenCalledTimes(1);
    expect(createFromOptionsMock).toHaveBeenCalledTimes(1);
  });

  it('sends exactly one AttentionSignalMessage per 5-second window while tutorState is TEACHING, with head_pose_score and behavioral_score genuinely derived from distinct inputs (AC-3, review finding)', async () => {
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

    // Cross-check against the pure functions applied to the same fixture --
    // a bug that swapped which sample array feeds head_pose_score vs. the
    // gaze component of behavioral_score would now fail this, since the two
    // inputs are deliberately distinct (unlike an identity-matrix/empty-
    // blendshapes fixture, where both evaluate to the same value).
    const expectedHeadPose = computeHeadPoseScore(MILD_YAW_MATRIX);
    const expectedGaze = computeGazeScore(MILD_LOOK_AWAY_BLENDSHAPES);
    expect(expectedHeadPose).not.toBeCloseTo(expectedGaze, 2);
    expect(msg.payload.head_pose_score).toBeCloseTo(expectedHeadPose, 5);
  });

  it('scores a completely absent face as worst-case attention, not perfect (AC-3, review finding)', async () => {
    detectForVideoMock.mockReturnValue(NO_FACE_RESULT);
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    await flush(5000);

    expect(sendMock).toHaveBeenCalledTimes(1);
    const [msg] = sendMock.mock.calls[0];
    // Previously `average([]) ?? 1` reported maximum attentiveness for a
    // student who was never in frame for the entire window -- both fields
    // must now reflect the worst case (0), not the best.
    expect(msg.payload.head_pose_score).toBe(0);
    expect(msg.payload.behavioral_score).toBeCloseTo(computeBehavioralScore(0, 'neutral', 0), 5);
  });

  it('sends no signal while tutorState is not TEACHING (AC-4)', async () => {
    usePlayerStore.setState({ tutorState: 'QUIZZING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    await flush(5000);

    expect(sendMock).not.toHaveBeenCalled();
  });

  it('resumes sending on the next window after returning to TEACHING, without re-initializing the camera/model (AC-4)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();
    act(() => usePlayerStore.setState({ tutorState: 'QUIZZING' }));
    await flush(5000);
    expect(sendMock).not.toHaveBeenCalled();

    act(() => usePlayerStore.setState({ tutorState: 'TEACHING' }));
    await flush(5000);

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(getUserMediaMock).toHaveBeenCalledTimes(1);
    expect(createFromOptionsMock).toHaveBeenCalledTimes(1);
  });

  it('does not throw and sends nothing when wsSendAttentionSignal is null (socket disconnected), and logs the drop once', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING', wsSendAttentionSignal: null });
    renderHook(() => useAttentionMonitor());
    await flush();

    await expect(flush(5000)).resolves.not.toThrow();
    expect(sendMock).not.toHaveBeenCalled();
    expect(console.warn).toHaveBeenCalledTimes(1);

    // A second consecutive drop must not log again (once per drop streak,
    // not once per window -- review finding, matches the story's own
    // documented intent).
    await flush(5000);
    expect(console.warn).toHaveBeenCalledTimes(1);
  });

  it('drops the signal and logs once when sessionId is still empty (session not yet minted), without sending an unassociated signal (review finding)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING', sessionId: '' });
    renderHook(() => useAttentionMonitor());
    await flush();

    await flush(5000);

    expect(sendMock).not.toHaveBeenCalled();
    expect(console.warn).toHaveBeenCalledTimes(1);
  });

  it('degrades gracefully and logs when MediaPipe fails to initialize (both GPU and CPU delegates), never throwing (AC-6)', async () => {
    createFromOptionsMock.mockRejectedValue(new Error('WASM load failed'));
    usePlayerStore.setState({ tutorState: 'TEACHING' });

    renderHook(() => useAttentionMonitor());
    await flush();
    await flush(5000);

    expect(console.error).toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('releases the camera stream if MediaPipe fails to initialize after the camera was already acquired (review finding)', async () => {
    createFromOptionsMock.mockRejectedValue(new Error('WASM load failed'));
    usePlayerStore.setState({ tutorState: 'TEACHING' });

    renderHook(() => useAttentionMonitor());
    await flush();

    expect(getUserMediaMock).toHaveBeenCalled();
    expect(fakeTrack.stop).toHaveBeenCalledTimes(1);
  });

  it('retries with the CPU delegate if the GPU delegate fails to initialize, and still succeeds (decision resolution, review finding)', async () => {
    createFromOptionsMock
      .mockRejectedValueOnce(new Error('GPU delegate unavailable'))
      .mockResolvedValueOnce({ detectForVideo: detectForVideoMock, close: closeMock });
    usePlayerStore.setState({ tutorState: 'TEACHING' });

    renderHook(() => useAttentionMonitor());
    await flush();

    expect(createFromOptionsMock).toHaveBeenCalledTimes(2);
    expect(createFromOptionsMock.mock.calls[0][1].baseOptions.delegate).toBe('GPU');
    expect(createFromOptionsMock.mock.calls[1][1].baseOptions.delegate).toBe('CPU');
    expect(console.error).toHaveBeenCalled();

    await flush(5000);
    expect(sendMock).toHaveBeenCalledTimes(1);
  });

  it('corrects blink_rate for real elapsed wall-clock time instead of assuming exactly 5000ms between flushes (backgrounded-tab timer throttling, review finding)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    // One blink registers on the very next frame.
    detectForVideoMock.mockReturnValueOnce(
      faceDetectedResult(IDENTITY_MATRIX, [
        { categoryName: 'eyeBlinkLeft', score: 0.9 },
        { categoryName: 'eyeBlinkRight', score: 0.9 },
      ]),
    );

    // Jump the clock forward well past the nominal 5000ms window WITHOUT
    // advancing timers first, simulating a backgrounded/throttled tab where
    // the interval fires much later than its nominal schedule but Date.now()
    // still reflects the real gap.
    vi.setSystemTime(Date.now() + 60000);
    await flush(5000);

    expect(sendMock).toHaveBeenCalledTimes(1);
    const [msg] = sendMock.mock.calls[0];
    // The old fixed x12 multiplier would report exactly 12 for one blink
    // regardless of real elapsed time. With wall-clock correction, one blink
    // over a ~60s+ real gap must be far below that.
    expect(msg.payload.blink_rate).toBeLessThan(2);
  });

  it('a single frame that throws does not permanently kill the detection loop (review finding)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    detectForVideoMock.mockImplementationOnce(() => {
      throw new Error('transient GPU/WASM error');
    });

    await flush(5000);

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(console.error).toHaveBeenCalled();
  });

  it('stops the camera and closes the model on unmount (AC-7)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    const { unmount } = renderHook(() => useAttentionMonitor());
    await flush();

    unmount();

    expect(fakeTrack.stop).toHaveBeenCalledTimes(1);
    expect(closeMock).toHaveBeenCalledTimes(1);
  });

  it('stops the camera when the underlying track ends unexpectedly (OS permission revoked / camera unplugged, review finding)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();

    expect(fakeTrack.onended).toBeTypeOf('function');
    act(() => fakeTrack.onended!());

    expect(closeMock).toHaveBeenCalledTimes(1);
    sendMock.mockClear();
    await flush(5000);
    expect(sendMock).not.toHaveBeenCalled();
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

  it('leaves zero pending timers after SESSION_END teardown -- not just "no more sends" (review finding: windowTimer previously leaked if assigned after the first detectFrame() call already observed SESSION_END)', async () => {
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    renderHook(() => useAttentionMonitor());
    await flush();
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    act(() => usePlayerStore.setState({ tutorState: 'SESSION_END' }));
    await flush(100);

    expect(closeMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
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

  it('does not proceed to load the model if unmounted while getUserMedia is still resolving (tornDown race guard, review finding)', async () => {
    let resolveGetUserMedia!: (v: { getTracks: () => { stop: ReturnType<typeof vi.fn> }[] }) => void;
    getUserMediaMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGetUserMedia = resolve;
        }),
    );
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    const { unmount } = renderHook(() => useAttentionMonitor());
    await flush(0);

    unmount();

    await act(async () => {
      resolveGetUserMedia({ getTracks: () => [fakeTrack] });
      await Promise.resolve();
    });

    expect(fakeTrack.stop).toHaveBeenCalledTimes(1);
    expect(createFromOptionsMock).not.toHaveBeenCalled();
  });

  it('does not start the detection loop if unmounted while createFaceLandmarker is still resolving (tornDown race guard, review finding)', async () => {
    let resolveCreate!: (v: { detectForVideo: typeof detectForVideoMock; close: typeof closeMock }) => void;
    createFromOptionsMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        }),
    );
    usePlayerStore.setState({ tutorState: 'TEACHING' });
    const { unmount } = renderHook(() => useAttentionMonitor());
    await flush(0);

    unmount();

    await act(async () => {
      resolveCreate({ detectForVideo: detectForVideoMock, close: closeMock });
      await Promise.resolve();
    });

    expect(closeMock).toHaveBeenCalledTimes(1);
    sendMock.mockClear();
    await flush(5000);
    expect(sendMock).not.toHaveBeenCalled();
  });
});
