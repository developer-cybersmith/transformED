'use client'

import { useRef, useState, useCallback, useEffect } from 'react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AttentionSignals {
  /** Behavioral engagement: tab visibility + interaction events (0–1) */
  behavioral_score: number
  /** Head pose score derived from face landmarks (0–1, 1 = facing screen) */
  head_pose_score: number
  /** Blink rate per minute, normalized to 0–1 (0.3 blinks/min → 0, 30 blinks/min → 1) */
  blink_rate: number
}

export interface UseMediaPipeReturn {
  startCapture: () => Promise<void>
  stopCapture: () => void
  latestSignals: AttentionSignals | null
  isCapturing: boolean
  error: string | null
}

// ---------------------------------------------------------------------------
// MediaPipe CDN path — served from @mediapipe/tasks-vision package
// ---------------------------------------------------------------------------
const WASM_PATH = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
const MODEL_ASSET_PATH =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'

// ---------------------------------------------------------------------------
// Landmark index constants (MediaPipe 478-point mesh)
// ---------------------------------------------------------------------------

// Nose tip: landmark 1
// Left eye: 33 (outer), 159 (upper-mid), 145 (lower-mid), 133 (inner)
// Right eye: 362 (outer), 386 (upper-mid), 374 (lower-mid), 263 (inner)
// Left iris centre: 468
// Right iris centre: 473
// Chin: 152
// Forehead: 10

const NOSE_TIP = 1
const LEFT_EYE_OUTER = 33
const LEFT_EYE_INNER = 133
const LEFT_EYE_TOP = 159
const LEFT_EYE_BOT = 145
const RIGHT_EYE_OUTER = 362
const RIGHT_EYE_INNER = 263
const RIGHT_EYE_TOP = 386
const RIGHT_EYE_BOT = 374
const CHIN = 152
const FOREHEAD = 10

// Normalised EAR (Eye Aspect Ratio) threshold below which a blink is detected
const BLINK_EAR_THRESHOLD = 0.22
// Minimum ms a blink must last to be counted (avoids noise)
const BLINK_MIN_DURATION_MS = 50

// ---------------------------------------------------------------------------
// Utility: Eye Aspect Ratio
// ---------------------------------------------------------------------------

interface Pt { x: number; y: number; z?: number }

function dist2d(a: Pt, b: Pt): number {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
}

function eyeAspectRatio(top: Pt, bot: Pt, inner: Pt, outer: Pt): number {
  const vertical = dist2d(top, bot)
  const horizontal = dist2d(inner, outer)
  return horizontal > 0 ? vertical / horizontal : 0
}

// ---------------------------------------------------------------------------
// Utility: Head pose from 3D landmarks
//
// We approximate yaw (left-right) and pitch (up-down) using the ratio of
// distances from the nose tip to eye-corners and to chin/forehead.
// Score 1.0 = fully facing screen. Degrades as the head turns.
// ---------------------------------------------------------------------------

function computeHeadPoseScore(lm: Pt[]): number {
  const nose = lm[NOSE_TIP]
  const leftEye = lm[LEFT_EYE_OUTER]
  const rightEye = lm[RIGHT_EYE_OUTER]
  const chin = lm[CHIN]
  const forehead = lm[FOREHEAD]

  if (!nose || !leftEye || !rightEye || !chin || !forehead) return 0.5

  // Yaw: compare horizontal distances nose→left vs nose→right eye corner
  const dLeft = nose.x - leftEye.x
  const dRight = rightEye.x - nose.x
  const yawRatio = Math.min(dLeft, dRight) / (Math.max(dLeft, dRight) + 1e-6)

  // Pitch: compare vertical distances nose→forehead vs nose→chin
  const dUp = nose.y - forehead.y
  const dDown = chin.y - nose.y
  const pitchRatio = Math.min(dUp, dDown) / (Math.max(dUp, dDown) + 1e-6)

  // Both ratios are 1.0 when perfectly centred; degrade quadratically toward 0
  const yawScore = Math.max(0, Math.min(1, yawRatio))
  const pitchScore = Math.max(0, Math.min(1, pitchRatio))

  return (yawScore + pitchScore) / 2
}

// ---------------------------------------------------------------------------
// Behavioral scoring (no camera needed — tab visibility + interactions)
// ---------------------------------------------------------------------------

class BehavioralScorer {
  private interactionCount = 0
  private visibilityTime = 0
  private totalTime = 0
  private lastTick = Date.now()
  private hidden = false

  constructor() {
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this.onVisibilityChange)
      document.addEventListener('mousemove', this.onInteraction, { passive: true })
      document.addEventListener('keydown', this.onInteraction, { passive: true })
      document.addEventListener('scroll', this.onInteraction, { passive: true })
    }
  }

  private onVisibilityChange = () => {
    this.tick()
    this.hidden = document.hidden
  }

  private onInteraction = () => {
    this.interactionCount++
  }

  private tick() {
    const now = Date.now()
    const dt = now - this.lastTick
    this.totalTime += dt
    if (!this.hidden) this.visibilityTime += dt
    this.lastTick = now
  }

  collect(): number {
    this.tick()

    const visibilityRatio = this.totalTime > 0 ? this.visibilityTime / this.totalTime : 1
    // Normalize interactions: 0 → 0, ≥20 → 1 (per window)
    const interactionRatio = Math.min(1, this.interactionCount / 20)

    // Reset counters for the next window
    this.interactionCount = 0
    this.visibilityTime = 0
    this.totalTime = 0
    this.lastTick = Date.now()

    return 0.7 * visibilityRatio + 0.3 * interactionRatio
  }

  destroy() {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.onVisibilityChange)
      document.removeEventListener('mousemove', this.onInteraction)
      document.removeEventListener('keydown', this.onInteraction)
      document.removeEventListener('scroll', this.onInteraction)
    }
  }
}

// ---------------------------------------------------------------------------
// Main hook
// ---------------------------------------------------------------------------

export function useMediaPipe(): UseMediaPipeReturn {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [latestSignals, setLatestSignals] = useState<AttentionSignals | null>(null)

  // Refs — survive re-renders, not tracked by React
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const landmarkerRef = useRef<unknown>(null) // FaceLandmarker instance
  const rafRef = useRef<number | null>(null)
  const behavioralRef = useRef<BehavioralScorer | null>(null)

  // Blink detection state
  const blinkCountRef = useRef(0)
  const inBlinkRef = useRef(false)
  const blinkStartRef = useRef(0)
  const windowStartRef = useRef(Date.now())

  // Aggregation window (5s)
  const WINDOW_MS = 5000
  const headPoseSamplesRef = useRef<number[]>([])

  // ── Load MediaPipe FaceLandmarker (lazy — only when camera permission granted) ──
  async function loadLandmarker() {
    if (landmarkerRef.current) return landmarkerRef.current

    // Dynamic import to avoid SSR issues
    const { FaceLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision')

    const vision = await FilesetResolver.forVisionTasks(WASM_PATH)

    const landmarker = await FaceLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: MODEL_ASSET_PATH,
        delegate: 'GPU',
      },
      runningMode: 'VIDEO',
      numFaces: 1,
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: false,
    })

    landmarkerRef.current = landmarker
    return landmarker
  }

  // ── Main detection loop ──────────────────────────────────────────────────
  function runDetection() {
    const video = videoRef.current
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const landmarker = landmarkerRef.current as any

    if (!video || !landmarker || video.readyState < 2) {
      rafRef.current = requestAnimationFrame(runDetection)
      return
    }

    const nowMs = performance.now()

    // Detect face landmarks
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const results: any = landmarker.detectForVideo(video, nowMs)
    const landmarks: Pt[][] = results?.faceLandmarks ?? []

    if (landmarks.length > 0) {
      const lm = landmarks[0]

      // ── Head pose ─────────────────────────────────────────────────────
      const headPose = computeHeadPoseScore(lm)
      headPoseSamplesRef.current.push(headPose)

      // ── Blink detection ───────────────────────────────────────────────
      const leftEAR = eyeAspectRatio(lm[LEFT_EYE_TOP], lm[LEFT_EYE_BOT], lm[LEFT_EYE_INNER], lm[LEFT_EYE_OUTER])
      const rightEAR = eyeAspectRatio(lm[RIGHT_EYE_TOP], lm[RIGHT_EYE_BOT], lm[RIGHT_EYE_INNER], lm[RIGHT_EYE_OUTER])
      const avgEAR = (leftEAR + rightEAR) / 2

      if (avgEAR < BLINK_EAR_THRESHOLD && !inBlinkRef.current) {
        inBlinkRef.current = true
        blinkStartRef.current = nowMs
      } else if (avgEAR >= BLINK_EAR_THRESHOLD && inBlinkRef.current) {
        inBlinkRef.current = false
        if (nowMs - blinkStartRef.current >= BLINK_MIN_DURATION_MS) {
          blinkCountRef.current++
        }
      }
    }

    // ── Aggregate every WINDOW_MS ─────────────────────────────────────────
    const windowElapsed = Date.now() - windowStartRef.current
    if (windowElapsed >= WINDOW_MS) {
      const samples = headPoseSamplesRef.current
      const avgHeadPose = samples.length > 0
        ? samples.reduce((a, b) => a + b, 0) / samples.length
        : 0.5

      // Blink rate: normalize — typical range 10–20 blinks/min → ~1 blink per 3-6s
      // In 5s window: 0 blinks → 0, ≥3 blinks → 1
      const blinkRate = Math.min(1, blinkCountRef.current / 3)

      const behavioralScore = behavioralRef.current?.collect() ?? 1

      setLatestSignals({
        behavioral_score: behavioralScore,
        head_pose_score: avgHeadPose,
        blink_rate: blinkRate,
      })

      // Reset window
      headPoseSamplesRef.current = []
      blinkCountRef.current = 0
      windowStartRef.current = Date.now()
    }

    rafRef.current = requestAnimationFrame(runDetection)
  }

  // ── startCapture ──────────────────────────────────────────────────────────
  const startCapture = useCallback(async () => {
    setError(null)

    try {
      // Request camera stream
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240, facingMode: 'user' },
        audio: false,
      })
      streamRef.current = stream

      // Create off-screen video element — raw video NEVER leaves this hook
      const video = document.createElement('video')
      video.srcObject = stream
      video.muted = true
      video.playsInline = true
      await video.play()
      videoRef.current = video

      // Load MediaPipe
      await loadLandmarker()

      // Start behavioral scorer
      behavioralRef.current = new BehavioralScorer()
      windowStartRef.current = Date.now()

      setIsCapturing(true)
      rafRef.current = requestAnimationFrame(runDetection)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Camera access failed'
      setError(msg)
      console.warn('[useMediaPipe] startCapture error:', err)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── stopCapture ────────────────────────────────────────────────────────────
  const stopCapture = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }

    const stream = streamRef.current
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null
      videoRef.current = null
    }

    behavioralRef.current?.destroy()
    behavioralRef.current = null

    setIsCapturing(false)
  }, [])

  // ── Cleanup on unmount ─────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      stopCapture()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(landmarkerRef.current as any)?.close?.()
      landmarkerRef.current = null
    }
  }, [stopCapture])

  return { startCapture, stopCapture, latestSignals, isCapturing, error }
}
