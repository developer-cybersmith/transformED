import { describe, it, expect } from 'vitest';
import {
  computeHeadPoseScore,
  computeGazeScore,
  classifyExpression,
  computeBehavioralScore,
  createBlinkCounter,
  getBlendshapeScore,
} from '@/lib/attention/signalMath';

function identityMatrix(): number[] {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}

function blendshapes(overrides: Record<string, number>): { categoryName: string; score: number }[] {
  return Object.entries(overrides).map(([categoryName, score]) => ({ categoryName, score }));
}

describe('signalMath', () => {
  describe('getBlendshapeScore', () => {
    it('returns the matching category score', () => {
      expect(getBlendshapeScore(blendshapes({ eyeBlinkLeft: 0.7 }), 'eyeBlinkLeft')).toBe(0.7);
    });

    it('returns 0 for a category not present (defensive against a MediaPipe result missing an expected shape)', () => {
      expect(getBlendshapeScore(blendshapes({ eyeBlinkLeft: 0.7 }), 'eyeBlinkRight')).toBe(0);
    });
  });

  describe('computeHeadPoseScore', () => {
    it('scores a dead-center (identity matrix) face as 1', () => {
      expect(computeHeadPoseScore(identityMatrix())).toBe(1);
    });

    it('scores a 30-degree yaw at or below 0 (story-specified threshold)', () => {
      const rad = (30 * Math.PI) / 180;
      // Column-major 4x4 rotation about Y axis by `rad`.
      const c = Math.cos(rad);
      const s = Math.sin(rad);
      const m = [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];
      expect(computeHeadPoseScore(m)).toBeLessThanOrEqual(0.01);
    });

    // Review finding (2026-08-10): the previous formula put a real Y-axis
    // head-turn (real yaw) entirely into the "pitch" slot and let Z-axis
    // rotation (roll/head-tilt) leak into the "yaw" slot -- both existing
    // tests above only exercise pure Y-axis rotations, so neither could
    // catch it. These two regression tests exercise the other two axes
    // independently to prove the fix actually separates them.
    it('a pure X-axis rotation (real head pitch/nod) is measured, and does not leak into the yaw axis', () => {
      const rad = (30 * Math.PI) / 180;
      const c = Math.cos(rad);
      const s = Math.sin(rad);
      // Column-major 4x4 rotation about X axis by `rad`.
      const m = [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1];
      // A pure 30-degree pitch alone must clamp the score to 0 via the
      // (tighter) PITCH_THRESHOLD_DEG=20 axis, same as the yaw test above
      // clamps via YAW_THRESHOLD_DEG=30 -- if pitch were still inert (the
      // bug), this would incorrectly score 1 (dead-center).
      expect(computeHeadPoseScore(m)).toBeLessThanOrEqual(0.01);
    });

    it('a pure Z-axis rotation (roll/head-tilt) does not affect the score at all -- roll is explicitly out of spec', () => {
      const rad = (30 * Math.PI) / 180;
      const c = Math.cos(rad);
      const s = Math.sin(rad);
      // Column-major 4x4 rotation about Z axis by `rad`.
      const m = [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
      // If roll were still leaking into the yaw axis (the bug), a 30-degree
      // roll alone would clamp this to 0 instead of leaving it at 1.
      expect(computeHeadPoseScore(m)).toBe(1);
    });

    it('scores a small deviation (5 degrees) close to but below 1', () => {
      const rad = (5 * Math.PI) / 180;
      const c = Math.cos(rad);
      const s = Math.sin(rad);
      const m = [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];
      const score = computeHeadPoseScore(m);
      expect(score).toBeGreaterThan(0.7);
      expect(score).toBeLessThan(1);
    });
  });

  describe('computeGazeScore', () => {
    it('scores 1 when no look-away blendshapes are active', () => {
      expect(computeGazeScore([])).toBe(1);
    });

    it('scores lower when look-away blendshapes are highly active', () => {
      const cats = blendshapes({
        eyeLookOutLeft: 0.9,
        eyeLookOutRight: 0.9,
      });
      expect(computeGazeScore(cats)).toBeLessThan(0.8);
    });
  });

  describe('classifyExpression', () => {
    it('classifies neutral by default', () => {
      expect(classifyExpression([])).toBe('neutral');
    });

    it('classifies confused when brow-down blendshapes are high', () => {
      const cats = blendshapes({ browDownLeft: 0.8, browDownRight: 0.8 });
      expect(classifyExpression(cats)).toBe('confused');
    });

    it('classifies surprised when eye-wide + brow-inner-up are both high', () => {
      const cats = blendshapes({ eyeWideLeft: 0.7, eyeWideRight: 0.7, browInnerUp: 0.7 });
      expect(classifyExpression(cats)).toBe('surprised');
    });
  });

  describe('computeBehavioralScore', () => {
    it('scores 1 for perfect gaze, neutral expression, and baseline+ interaction', () => {
      expect(computeBehavioralScore(1, 'neutral', 10)).toBe(1);
    });

    it('penalizes confused expression relative to neutral, all else equal', () => {
      const neutral = computeBehavioralScore(1, 'neutral', 10);
      const confused = computeBehavioralScore(1, 'confused', 10);
      expect(confused).toBeLessThan(neutral);
    });

    it('penalizes zero interaction relative to baseline interaction', () => {
      const withInteraction = computeBehavioralScore(1, 'neutral', 10);
      const noInteraction = computeBehavioralScore(1, 'neutral', 0);
      expect(noInteraction).toBeLessThan(withInteraction);
    });

    it('never exceeds 1 even with interaction far above baseline', () => {
      expect(computeBehavioralScore(1, 'neutral', 1000)).toBeLessThanOrEqual(1);
    });
  });

  describe('createBlinkCounter', () => {
    it('counts a rising-edge blink exactly once, not once per sustained frame', () => {
      const counter = createBlinkCounter();
      const closed = blendshapes({ eyeBlinkLeft: 0.9, eyeBlinkRight: 0.9 });
      const open = blendshapes({ eyeBlinkLeft: 0.0, eyeBlinkRight: 0.0 });

      counter.update(open);
      counter.update(closed); // rising edge #1
      counter.update(closed); // still closed -- same blink, must not double-count
      counter.update(closed);
      counter.update(open);

      expect(counter.count).toBe(1);
    });

    it('counts two separate blinks separated by an open frame', () => {
      const counter = createBlinkCounter();
      const closed = blendshapes({ eyeBlinkLeft: 0.9, eyeBlinkRight: 0.9 });
      const open = blendshapes({ eyeBlinkLeft: 0.0, eyeBlinkRight: 0.0 });

      counter.update(open);
      counter.update(closed);
      counter.update(open);
      counter.update(closed);
      counter.update(open);

      expect(counter.count).toBe(2);
    });

    it('does not count a blink when only one eye crosses the threshold', () => {
      const counter = createBlinkCounter();
      const oneEyed = blendshapes({ eyeBlinkLeft: 0.9, eyeBlinkRight: 0.1 });

      counter.update(blendshapes({ eyeBlinkLeft: 0, eyeBlinkRight: 0 }));
      counter.update(oneEyed);

      expect(counter.count).toBe(0);
    });

    it('reset() zeroes the count and clears prior blink state', () => {
      const counter = createBlinkCounter();
      const closed = blendshapes({ eyeBlinkLeft: 0.9, eyeBlinkRight: 0.9 });
      const open = blendshapes({ eyeBlinkLeft: 0.0, eyeBlinkRight: 0.0 });

      counter.update(open);
      counter.update(closed);
      expect(counter.count).toBe(1);

      counter.reset();
      expect(counter.count).toBe(0);

      // A frame already "closed" at reset must still register a fresh rising
      // edge on the next open->closed transition, not be treated as already-blinking.
      counter.update(open);
      counter.update(closed);
      expect(counter.count).toBe(1);
    });
  });
});
