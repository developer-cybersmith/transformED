'use client';

import { useEffect, useRef } from 'react';
import type { AttentionSignalMessage } from '@hie/shared/types/ws';
import { useAttentionConsent } from './useAttentionConsent';
import { usePlayerStore } from '@/stores/player.machine';
import {
  type BlendshapeCategory,
  type ExpressionLabel,
  computeHeadPoseScore,
  computeGazeScore,
  classifyExpression,
  computeBehavioralScore,
  createBlinkCounter,
} from '@/lib/attention/signalMath';

const FRAME_INTERVAL_MS = 1000 / 30;
const AGGREGATION_WINDOW_MS = 5000;
const WASM_BASE_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10/wasm';
const MODEL_ASSET_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task';

interface FaceLandmarkerResultLike {
  faceBlendshapes?: { categories: BlendshapeCategory[] }[];
  facialTransformationMatrixes?: { data: number[] }[];
}

interface FaceLandmarkerLike {
  detectForVideo: (video: HTMLVideoElement, timestampMs: number) => FaceLandmarkerResultLike;
  close: () => void;
}

/**
 * Lazily imported (not a static top-level import) so the WASM-loading module
 * is only ever pulled in once consent is confirmed, and so tests can mock
 * `@mediapipe/tasks-vision` at the module level without it loading real WASM.
 */
async function createFaceLandmarker(): Promise<FaceLandmarkerLike> {
  const { FaceLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision');
  const vision = await FilesetResolver.forVisionTasks(WASM_BASE_URL);
  return FaceLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: MODEL_ASSET_URL, delegate: 'GPU' },
    outputFaceBlendshapes: true,
    outputFacialTransformationMatrixes: true,
    runningMode: 'VIDEO',
    numFaces: 1,
  }) as unknown as Promise<FaceLandmarkerLike>;
}

function average(samples: number[]): number | null {
  if (samples.length === 0) return null;
  return samples.reduce((sum, v) => sum + v, 0) / samples.length;
}

function pickDominantExpression(counts: Record<ExpressionLabel, number>): ExpressionLabel {
  let dominant: ExpressionLabel = 'neutral';
  let max = -1;
  (Object.keys(counts) as ExpressionLabel[]).forEach((label) => {
    if (counts[label] > max) {
      max = counts[label];
      dominant = label;
    }
  });
  return dominant;
}

/**
 * S3-02. Locally runs MediaPipe FaceLandmarker against the student's camera
 * while `tutorState === 'TEACHING'` (CLAUDE.md's tutor guard rule: "CES
 * monitoring ONLY active in TEACHING state"), and sends an
 * AttentionSignalMessage every 5 seconds. Raw video NEVER leaves the browser
 * -- only the 5 aggregated numbers in the frozen wire contract are sent.
 *
 * Consent-gated on `useAttentionConsent().consentStatus === 'accepted'`
 * (never `showModal` -- that hook's own docstring forbids using it as a
 * security gate). Calling `useAttentionConsent()` here gives this hook its
 * own fresh mount-time Supabase read, per that hook's "fresh read of its
 * own" requirement, without duplicating the query.
 */
export function useAttentionMonitor(): void {
  const { consentStatus, isLoading: consentLoading } = useAttentionConsent();
  const tutorState = usePlayerStore((s) => s.tutorState);

  // Read fresh inside the frame/window loops without re-running the whole
  // init effect on every tutorState/sessionId change (AC-4: pausing must not
  // tear down and re-initialize the camera/model).
  const tutorStateRef = useRef(tutorState);
  useEffect(() => {
    tutorStateRef.current = tutorState;
  }, [tutorState]);

  const sessionIdRef = useRef(usePlayerStore.getState().sessionId);
  useEffect(
    () =>
      usePlayerStore.subscribe((state) => {
        sessionIdRef.current = state.sessionId;
      }),
    [],
  );

  useEffect(() => {
    // AC-2/AC-8: never initialize before consent resolves to 'accepted'.
    if (consentLoading || consentStatus !== 'accepted') return;

    let tornDown = false;
    let stream: MediaStream | null = null;
    let landmarker: FaceLandmarkerLike | null = null;
    let video: HTMLVideoElement | null = null;
    let frameTimer: ReturnType<typeof setTimeout> | null = null;
    let windowTimer: ReturnType<typeof setInterval> | null = null;

    const blinkCounter = createBlinkCounter();
    let headPoseSamples: number[] = [];
    let gazeSamples: number[] = [];
    let expressionCounts: Record<ExpressionLabel, number> = { neutral: 0, confused: 0, surprised: 0 };
    let interactionEventCount = 0;

    function trackInteraction(): void {
      interactionEventCount += 1;
    }

    function resetWindow(): void {
      headPoseSamples = [];
      gazeSamples = [];
      expressionCounts = { neutral: 0, confused: 0, surprised: 0 };
      interactionEventCount = 0;
      blinkCounter.reset();
    }

    // AC-7: stops the camera/model exactly once, whether triggered by
    // unmount or by tutorState reaching SESSION_END -- never on every
    // TEACHING pause (AC-4), which only stops sampling, not the stream.
    function teardown(): void {
      if (tornDown) return;
      tornDown = true;
      window.removeEventListener('click', trackInteraction);
      window.removeEventListener('scroll', trackInteraction);
      window.removeEventListener('mousemove', trackInteraction);
      if (frameTimer) clearTimeout(frameTimer);
      if (windowTimer) clearInterval(windowTimer);
      stream?.getTracks().forEach((track) => track.stop());
      landmarker?.close();
    }

    async function init(): Promise<void> {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true });
        if (tornDown) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        video = document.createElement('video');
        video.srcObject = stream;
        video.muted = true;
        try {
          await video.play();
        } catch {
          // Autoplay/permission quirks in some browsers -- detectForVideo
          // still works once the stream is attached; not a fatal error.
        }

        landmarker = await createFaceLandmarker();
        if (tornDown) {
          landmarker.close();
          return;
        }

        window.addEventListener('click', trackInteraction);
        window.addEventListener('scroll', trackInteraction);
        window.addEventListener('mousemove', trackInteraction);

        function detectFrame(): void {
          if (tornDown || !landmarker || !video) return;
          // AC-7: SESSION_END is a terminal state for this effect instance --
          // tear down fully rather than merely pausing (which AC-4 covers
          // for every other non-TEACHING state).
          if (tutorStateRef.current === 'SESSION_END') {
            teardown();
            return;
          }
          if (tutorStateRef.current === 'TEACHING') {
            const result = landmarker.detectForVideo(video, performance.now());
            const blendshapes = result.faceBlendshapes?.[0]?.categories ?? [];
            const matrix = result.facialTransformationMatrixes?.[0]?.data;
            if (matrix) headPoseSamples.push(computeHeadPoseScore(matrix));
            gazeSamples.push(computeGazeScore(blendshapes));
            expressionCounts[classifyExpression(blendshapes)] += 1;
            blinkCounter.update(blendshapes);
          }
          frameTimer = setTimeout(detectFrame, FRAME_INTERVAL_MS);
        }
        detectFrame();

        function flushWindow(): void {
          // AC-4: no signal while paused outside TEACHING; samples simply
          // don't accumulate during that time, so this window is empty.
          if (tutorStateRef.current !== 'TEACHING') {
            resetWindow();
            return;
          }
          const send = usePlayerStore.getState().wsSendAttentionSignal;
          if (!send) {
            // Socket not connected this window -- a signal is a live
            // snapshot, not a durable record; drop rather than queue a
            // signal that would misrepresent a now-stale moment later.
            resetWindow();
            return;
          }

          const msg: AttentionSignalMessage = {
            type: 'attention_signal',
            payload: {
              session_id: sessionIdRef.current,
              quiz_accuracy: null,
              teachback_score: null,
              behavioral_score: computeBehavioralScore(
                average(gazeSamples) ?? 1,
                pickDominantExpression(expressionCounts),
                interactionEventCount,
              ),
              head_pose_score: average(headPoseSamples) ?? 1,
              blink_rate: blinkCounter.count * (60000 / AGGREGATION_WINDOW_MS),
            },
          };
          send(msg);
          resetWindow();
        }
        windowTimer = setInterval(flushWindow, AGGREGATION_WINDOW_MS);
      } catch (err) {
        // AC-6: WASM/camera failure must never block or crash the lesson --
        // log and simply send no signals for this session.
        console.error('[useAttentionMonitor] failed to initialize', err);
      }
    }

    void init();

    return () => {
      teardown();
    };
  }, [consentLoading, consentStatus]);
}
