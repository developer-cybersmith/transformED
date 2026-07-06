import { describe, it, expect } from 'vitest';
import type { NarrationTimestamp } from '@hie/shared/types/lesson';
import { binarySearchTimestamps } from '@/lib/binarySearch';

function make30Timestamps(): NarrationTimestamp[] {
  return Array.from({ length: 30 }, (_, i) => ({
    slide_id: `sl_${i}`,
    start_ms: i * 1000,
    end_ms: (i + 1) * 1000,
  }));
}

describe('binarySearchTimestamps', () => {
  it('returns 0 for a single-timestamp array regardless of position', () => {
    const ts: NarrationTimestamp[] = [{ slide_id: 'sl_0', start_ms: 0, end_ms: 5000 }];
    expect(binarySearchTimestamps(ts, 0)).toBe(0);
    expect(binarySearchTimestamps(ts, 4999)).toBe(0);
  });

  it('returns 0 when currentMs is before the first timestamp', () => {
    const ts = make30Timestamps();
    expect(binarySearchTimestamps(ts, -100)).toBe(0);
  });

  it('returns the exact index when currentMs lands exactly on a start_ms boundary', () => {
    const ts = make30Timestamps();
    expect(binarySearchTimestamps(ts, 5000)).toBe(5);
    expect(binarySearchTimestamps(ts, 0)).toBe(0);
  });

  it('returns the containing index when currentMs is mid-slot', () => {
    const ts = make30Timestamps();
    expect(binarySearchTimestamps(ts, 5500)).toBe(5);
    expect(binarySearchTimestamps(ts, 999)).toBe(0);
  });

  it('returns the last index when currentMs is at or beyond the final timestamp', () => {
    const ts = make30Timestamps();
    expect(binarySearchTimestamps(ts, 29000)).toBe(29);
    expect(binarySearchTimestamps(ts, 999999)).toBe(29);
  });

  it('is exhaustively correct against a linear-scan reference across a 30-timestamp fixture', () => {
    const ts = make30Timestamps();
    function linearReference(timestamps: NarrationTimestamp[], currentMs: number): number {
      let result = 0;
      for (let i = 0; i < timestamps.length; i++) {
        if (timestamps[i].start_ms <= currentMs) result = i;
      }
      return result;
    }
    for (let ms = -500; ms <= 30500; ms += 137) {
      expect(binarySearchTimestamps(ts, ms)).toBe(linearReference(ts, ms));
    }
  });
});
