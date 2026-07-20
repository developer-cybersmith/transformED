import type { NarrationTimestamp } from '@hie/shared/types/lesson';

/**
 * Binary search: returns the index of the latest timestamp whose start_ms ≤ currentMs.
 * O(log n) — no linear scan.
 */
export function binarySearchTimestamps(
  timestamps: NarrationTimestamp[],
  currentMs: number,
): number {
  let lo = 0, hi = timestamps.length - 1, result = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (timestamps[mid].start_ms <= currentMs) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}
