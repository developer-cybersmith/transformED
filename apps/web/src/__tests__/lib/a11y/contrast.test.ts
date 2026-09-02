import { describe, it, expect } from 'vitest';
import { getContrastRatio, meetsWcagAA } from '@/lib/a11y/contrast';

describe('getContrastRatio / meetsWcagAA', () => {
  it('computes max contrast for black on white', () => {
    expect(getContrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0);
  });

  it('computes 1:1 contrast for identical colors', () => {
    expect(getContrastRatio('#525252', '#525252')).toBeCloseTo(1, 5);
  });

  it('is order-independent (background/foreground can be passed either way)', () => {
    expect(getContrastRatio('#525252', '#ffffff')).toBeCloseTo(
      getContrastRatio('#ffffff', '#525252'),
      5
    );
  });

  it('confirms the pre-fix color (neutral-400, #a3a3a3) failed WCAG AA body text on white', () => {
    expect(meetsWcagAA('#a3a3a3', '#ffffff')).toBe(false);
    expect(getContrastRatio('#a3a3a3', '#ffffff')).toBeLessThan(4.5);
  });

  it('confirms the post-fix color (neutral-600, #525252) meets WCAG AA body text on white', () => {
    expect(meetsWcagAA('#525252', '#ffffff')).toBe(true);
    expect(getContrastRatio('#525252', '#ffffff')).toBeGreaterThanOrEqual(4.5);
  });

  it('applies the 3:1 large-text threshold when isLargeText is true', () => {
    // A gray that fails the 4.5:1 body threshold but clears 3:1 for large text.
    expect(meetsWcagAA('#767676', '#ffffff', false)).toBe(true);
    expect(getContrastRatio('#949494', '#ffffff')).toBeGreaterThanOrEqual(3);
    expect(meetsWcagAA('#949494', '#ffffff', false)).toBe(false);
    expect(meetsWcagAA('#949494', '#ffffff', true)).toBe(true);
  });
});
