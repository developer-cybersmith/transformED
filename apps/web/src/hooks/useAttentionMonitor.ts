'use client';

import { useEffect, useRef, useState } from 'react';
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
// Pinned to the exact installed npm version (apps/web/package.json) -- a
// mismatched WASM/JS version pairing is an unverified cross-version risk
// with no test coverage possible here (real WASM can't run under vitest).
const WASM_BASE_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm';
// DEFER-012 / D63 (docs/DEFECT-REGISTER.md): floating `latest` tag, not
// pinned to a specific model version -- see docs/deferred-work.md.
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
 *
 * Tries the GPU delegate first; if that fails to initialize (older hardware,
 * some mobile browsers, VDI/remote-desktop setups), retries once with the
 * CPU delegate before letting the caller's AC-6 fallback take over.
 */
async function createFaceLandmarker(): Promise<FaceLandmarkerLike> {
  const { FaceLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision');
  const vision = await FilesetResolver.forVisionTasks(WASM_BASE_URL);
  const baseOptions = {
    outputFaceBlendshapes: true,
    outputFacialTransformationMatrixes: true,
    runningMode: 'VIDEO' as const,
    numFaces: 1,
  };
  try {
    return (await FaceLandmarker.createFromOptions(vision, {
      ...baseOptions,
      baseOptions: { modelAssetPath: MODEL_ASSET_URL, delegate: 'GPU' },
    })) as FaceLandmarkerLike;
  } catch (gpuErr) {
    console.error('[useAttentionMonitor] GPU delegate failed, retrying with CPU delegate', gpuErr);
    return (await FaceLandmarker.createFromOptions(vision, {
      ...baseOptions,
      baseOptions: { modelAssetPath: MODEL_ASSET_URL, delegate: 'CPU' },
    })) as FaceLandmarkerLike;
  }
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
 *
 * Camera/model acquisition (AC-1) additionally waits for `tutorState` to
 * reach `'TEACHING'` at least once -- gating on consent alone would activate
 * the camera the instant a returning student (consent already accepted)
 * loads the player, before the lesson has even started (review finding,
 * confirmed independently by 6 of 8 review layers).
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

  // AC-1: flips false -> true exactly once, the first time tutorState
  // reaches 'TEACHING', and never resets -- so init fires on that
  // transition (not on raw consent alone) but never re-fires or tears down
  // on a later pause (AC-4 already owns that distinction).
  const [hasReachedTeaching, setHasReachedTeaching] = useState(tutorState === 'TEACHING');
  useEffect(() => {
    // Deliberately synchronous, same reasoning as the lesson-socket hook's
    // own connection-status sync -- this flips a one-way flag exactly once,
    // not a loop, so the "cascading renders" concern the rule generally
    // guards against does not apply here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (tutorState === 'TEACHING') setHasReachedTeaching(true);
  }, [tutorState]);

  useEffect(() => {
    // AC-1/AC-2/AC-8: never initialize before consent resolves to 'accepted'
    // AND tutorState has reached 'TEACHING' at least once.
    if (consentLoading || consentStatus !== 'accepted' || !hasReachedTeaching) return;

    let tornDown = false;
    let stream: MediaStream | null = null;
    let landmarker: FaceLandmarkerLike | null = null;
    let video: HTMLVideoElement | null = null;
    let frameTimer: ReturnType<typeof setTimeout> | null = null;
    let windowTimer: ReturnType<typeof setInterval> | null = null;
    let lastFlushAt = Date.now();
    // Logs a dropped-signal reason once per contiguous drop streak, not once
    // per window, matching this file's own documented "logged once, not per
    // window" intent (review finding: this logging previously didn't exist).
    let lastDropLogged = false;

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
    // unmount, an init failure, or by tutorState reaching SESSION_END --
    // never on every TEACHING pause (AC-4), which only stops sampling, not
    // the stream.
    function teardown(): void {
      if (tornDown) return;
      tornDown = true;
      window.removeEventListener('click', trackInteraction);
      window.removeEventListener('scroll', trackInteraction);
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
        // A dead track (OS permission revoked, camera unplugged mid-session)
        // must stop monitoring explicitly rather than let detectForVideo
        // keep running against a frozen/dead video element.
        stream.getTracks().forEach((track) => {
          track.onended = () => {
            console.error('[useAttentionMonitor] camera track ended -- stopping attention monitoring');
            teardown();
          };
        });

        video = document.createElement('video');
        video.srcObject = stream;
        video.muted = true;
        try {
          await video.play();
        } catch {
          // Autoplay/permission quirks in some browsers -- detectForVideo
          // still works once the stream is attached; not a fatal error.
        }
        if (tornDown) return;

        landmarker = await createFaceLandmarker();
        if (tornDown) {
          landmarker.close();
          return;
        }

        window.addEventListener('click', trackInteraction);
        window.addEventListener('scroll', trackInteraction);

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
            try {
              const result = landmarker.detectForVideo(video, performance.now());
              // A frame with no detected face (student absent/out of frame/
              // camera covered) must score as the worst case, not the best --
              // the previous behavior (empty samples defaulting to 1 at
              // flush time) reported maximum attentiveness for exactly the
              // scenario this component exists to catch (review finding).
              const faceDetected = (result.faceBlendshapes?.length ?? 0) > 0;
              const blendshapes = faceDetected ? result.faceBlendshapes![0].categories : [];
              const matrix = result.facialTransformationMatrixes?.[0]?.data;
              headPoseSamples.push(faceDetected && matrix ? computeHeadPoseScore(matrix) : 0);
              gazeSamples.push(faceDetected ? computeGazeScore(blendshapes) : 0);
              if (faceDetected) {
                expressionCounts[classifyExpression(blendshapes)] += 1;
                blinkCounter.update(blendshapes);
              }
            } catch (err) {
              // A single bad frame (video not yet decoded, transient
              // GPU/WASM error) must not kill the whole detection loop --
              // skip this frame and keep the recursive timer alive.
              console.error('[useAttentionMonitor] detectForVideo failed for a frame -- skipping', err);
            }
          }
          frameTimer = setTimeout(detectFrame, FRAME_INTERVAL_MS);
        }

        // windowTimer is assigned BEFORE the first detectFrame() call so
        // that if that first call observes tutorState already at
        // SESSION_END and tears down synchronously, the real interval
        // instance is already in scope for clearInterval to cancel --
        // previously this order was reversed, so an early SESSION_END could
        // clear a still-null `windowTimer` and leak the interval that got
        // assigned immediately afterward, running forever (review finding).
        function flushWindow(): void {
          const now = Date.now();
          const elapsedMs = Math.max(now - lastFlushAt, 1);
          lastFlushAt = now;

          // AC-4: no signal while paused outside TEACHING; samples simply
          // don't accumulate during that time, so this window is empty.
          if (tutorStateRef.current !== 'TEACHING') {
            resetWindow();
            return;
          }
          const send = usePlayerStore.getState().wsSendAttentionSignal;
          const sessionId = sessionIdRef.current;
          if (!send || !sessionId) {
            // A signal is a live snapshot, not a durable record; drop rather
            // than queue one that would misrepresent a now-stale moment
            // later. Logged once per drop streak (not per-window, to avoid
            // spamming the console for the rest of a disconnected session).
            if (!lastDropLogged) {
              console.warn(
                '[useAttentionMonitor] dropping attention signal --',
                !send ? 'no active socket connection' : 'session not yet created',
              );
              lastDropLogged = true;
            }
            resetWindow();
            return;
          }
          lastDropLogged = false;

          const msg: AttentionSignalMessage = {
            type: 'attention_signal',
            payload: {
              session_id: sessionId,
              quiz_accuracy: null,
              teachback_score: null,
              behavioral_score: computeBehavioralScore(
                average(gazeSamples) ?? 0,
                pickDominantExpression(expressionCounts),
                interactionEventCount,
              ),
              head_pose_score: average(headPoseSamples) ?? 0,
              // Wall-clock corrected rather than assuming exactly
              // AGGREGATION_WINDOW_MS between flushes -- a backgrounded/
              // throttled tab can push real elapsed time well past 5s, and
              // the fixed x12 multiplier this replaced would overstate the
              // rate by that same factor with no error or warning (review
              // finding, Scale & Load Hunter).
              blink_rate: blinkCounter.count * (60000 / elapsedMs),
            },
          };
          send(msg);
          resetWindow();
        }
        windowTimer = setInterval(flushWindow, AGGREGATION_WINDOW_MS);
        detectFrame();
      } catch (err) {
        // AC-6: WASM/camera failure must never block or crash the lesson --
        // log and release whatever was already partially acquired (e.g. the
        // camera stream, if createFaceLandmarker is what failed) rather than
        // leaving the camera-in-use indicator lit with nothing monitoring.
        console.error('[useAttentionMonitor] failed to initialize', err);
        teardown();
      }
    }

    void init();

    return () => {
      teardown();
    };
  }, [consentLoading, consentStatus, hasReachedTeaching]);
}
