/**
 * Pure signal-derivation functions for AttentionMonitor (S3-02). Deliberately
 * separated from the hook so the math is unit-testable with fixture
 * landmark/blendshape data, without mocking MediaPipe or a camera at all.
 *
 * First-pass heuristics -- not calibrated against real usage data (none
 * exists yet), same honest position CLAUDE.md already takes on the
 * server-side CES weights ("tunable post-calibration"). See
 * docs/stories/2-44-attention-monitor.md Dev Notes for the reasoning behind
 * each formula.
 */

export interface BlendshapeCategory {
  categoryName: string;
  score: number;
}

export type ExpressionLabel = 'neutral' | 'confused' | 'surprised';

const YAW_THRESHOLD_DEG = 30;
const PITCH_THRESHOLD_DEG = 20;
const BLINK_THRESHOLD = 0.5;
const EXPRESSION_HIGH_THRESHOLD = 0.4;
// Heuristic baseline for "normal" interaction volume in one 5-second window;
// calibration deferred (no usage data exists yet).
const INTERACTION_BASELINE_EVENTS_PER_WINDOW = 10;

const GAZE_BLENDSHAPES = [
  'eyeLookInLeft',
  'eyeLookOutLeft',
  'eyeLookUpLeft',
  'eyeLookDownLeft',
  'eyeLookInRight',
  'eyeLookOutRight',
  'eyeLookUpRight',
  'eyeLookDownRight',
];

const EXPRESSION_PENALTY: Record<ExpressionLabel, number> = {
  neutral: 0,
  confused: 0.3,
  surprised: 0.15,
};

export function getBlendshapeScore(categories: BlendshapeCategory[], name: string): number {
  return categories.find((c) => c.categoryName === name)?.score ?? 0;
}

/**
 * Extracts yaw/pitch (degrees) from a MediaPipe facialTransformationMatrix --
 * a column-major 4x4 matrix (16 floats), in MediaPipe's Y-up head-pose axis
 * convention (Y = vertical/yaw axis, X = horizontal/pitch axis, Z = depth/
 * roll axis). Uses the Y-X-Z Tait-Bryan decomposition (R = Ry(yaw) *
 * Rx(pitch) * Rz(roll)) that matches this convention -- NOT the aerospace
 * Z-Y-X ("first-extracted-angle-is-about-Z") convention, which is a
 * different axis order and gives yaw/pitch/roll different meanings. Roll is
 * unused (not part of the story's spec).
 *
 * Review finding (2026-08-10): an earlier version used the aerospace Z-Y-X
 * formulas here, which put a real head-turn (rotation about Y) entirely into
 * the "pitch" slot and let roll (head-tilt) leak into the "yaw" slot --
 * verified independently by two reviewers via matrix algebra. Fixed by
 * switching to the Y-X-Z decomposition and adding regression tests for pure
 * X-axis (real pitch) and pure Z-axis (roll, must not leak into yaw) inputs,
 * which the previous tests (pure Y-axis only) could not have caught.
 */
function extractYawPitchDegrees(matrixData: ArrayLike<number>): { yawDeg: number; pitchDeg: number } {
  const r01 = matrixData[4];
  const r11 = matrixData[5];
  const r20 = matrixData[2];
  const r21 = matrixData[6];
  const r22 = matrixData[10];

  const yawRad = Math.atan2(-r20, r22);
  const pitchRad = Math.atan2(-r21, Math.sqrt(r01 * r01 + r11 * r11));

  return { yawDeg: (yawRad * 180) / Math.PI, pitchDeg: (pitchRad * 180) / Math.PI };
}

/**
 * Score = 1 at dead-center, linearly decreasing to 0 at +/-30deg yaw or
 * +/-20deg pitch (whichever axis is worse dominates), clamped to [0, 1].
 */
export function computeHeadPoseScore(matrixData: ArrayLike<number>): number {
  const { yawDeg, pitchDeg } = extractYawPitchDegrees(matrixData);
  const yawScore = Math.max(0, 1 - Math.abs(yawDeg) / YAW_THRESHOLD_DEG);
  const pitchScore = Math.max(0, 1 - Math.abs(pitchDeg) / PITCH_THRESHOLD_DEG);
  return Math.min(yawScore, pitchScore);
}

/** 1 minus the average activation of the 8 "look away from center" blendshapes. */
export function computeGazeScore(categories: BlendshapeCategory[]): number {
  const avgDeviation =
    GAZE_BLENDSHAPES.reduce((sum, name) => sum + getBlendshapeScore(categories, name), 0) /
    GAZE_BLENDSHAPES.length;
  return Math.max(0, 1 - avgDeviation);
}

export function classifyExpression(categories: BlendshapeCategory[]): ExpressionLabel {
  const eyeWide =
    (getBlendshapeScore(categories, 'eyeWideLeft') + getBlendshapeScore(categories, 'eyeWideRight')) / 2;
  const browInnerUp = getBlendshapeScore(categories, 'browInnerUp');
  if (eyeWide > EXPRESSION_HIGH_THRESHOLD && browInnerUp > EXPRESSION_HIGH_THRESHOLD) return 'surprised';

  const browDown =
    (getBlendshapeScore(categories, 'browDownLeft') + getBlendshapeScore(categories, 'browDownRight')) / 2;
  if (browDown > EXPRESSION_HIGH_THRESHOLD) return 'confused';

  return 'neutral';
}

/**
 * Equal-thirds average of gaze, expression, and normalized DOM-interaction
 * rate. `gaze_score` and `expression_label` have no field on the frozen wire
 * contract (packages/shared/types/ws.ts) -- this is how they get folded into
 * the one transmittable `behavioral_score` number.
 */
export function computeBehavioralScore(
  gazeScore: number,
  expression: ExpressionLabel,
  interactionEventCount: number,
): number {
  const expressionScore = Math.max(0, 1 - EXPRESSION_PENALTY[expression]);
  const interactionScore = Math.min(1, interactionEventCount / INTERACTION_BASELINE_EVENTS_PER_WINDOW);
  return (gazeScore + expressionScore + interactionScore) / 3;
}

export interface BlinkCounter {
  readonly count: number;
  update: (categories: BlendshapeCategory[]) => void;
  reset: () => void;
}

/**
 * Counts discrete blinks via rising-edge detection (open -> closed), not
 * sustained-frame counting -- a single slow blink spans multiple ~33ms
 * frames at 30fps and must count once, not once per frame.
 */
export function createBlinkCounter(): BlinkCounter {
  let count = 0;
  let wasClosed = false;

  return {
    get count() {
      return count;
    },
    update(categories: BlendshapeCategory[]) {
      const isClosed =
        getBlendshapeScore(categories, 'eyeBlinkLeft') > BLINK_THRESHOLD &&
        getBlendshapeScore(categories, 'eyeBlinkRight') > BLINK_THRESHOLD;
      if (isClosed && !wasClosed) count += 1;
      wasClosed = isClosed;
    },
    reset() {
      count = 0;
      wasClosed = false;
    },
  };
}
