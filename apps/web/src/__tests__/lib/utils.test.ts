import { describe, it, expect } from 'vitest';
import { formatTimeAgo, formatCesLabel, formatTeachbackLabel } from '@/lib/utils';

describe('formatTimeAgo', () => {
  it('returns "Just now" for timestamps under a minute old', () => {
    expect(formatTimeAgo(new Date(Date.now() - 30_000).toISOString())).toBe('Just now');
  });

  it('formats minutes ago, singular vs plural', () => {
    expect(formatTimeAgo(new Date(Date.now() - 60_000).toISOString())).toBe('1 minute ago');
    expect(formatTimeAgo(new Date(Date.now() - 5 * 60_000).toISOString())).toBe('5 minutes ago');
  });

  it('formats hours ago, singular vs plural', () => {
    expect(formatTimeAgo(new Date(Date.now() - 60 * 60_000).toISOString())).toBe('1 hour ago');
    expect(formatTimeAgo(new Date(Date.now() - 2 * 60 * 60_000).toISOString())).toBe('2 hours ago');
  });

  it('formats days ago, singular vs plural', () => {
    expect(formatTimeAgo(new Date(Date.now() - 24 * 60 * 60_000).toISOString())).toBe('1 day ago');
    expect(formatTimeAgo(new Date(Date.now() - 3 * 24 * 60 * 60_000).toISOString())).toBe('3 days ago');
  });

  it('returns a fallback string instead of "NaN ... ago" for an invalid/empty date', () => {
    expect(formatTimeAgo('not-a-date')).toBe('Unknown');
    expect(formatTimeAgo('')).toBe('Unknown');
  });
});

describe('formatCesLabel — never returns a raw number, only a descriptive label', () => {
  it('bands: >=80 Highly Engaged, >=60 Well Focused, >=40 Getting There, <40 Room to Grow', () => {
    expect(formatCesLabel(100)).toBe('Highly Engaged');
    expect(formatCesLabel(80)).toBe('Highly Engaged');
    expect(formatCesLabel(79.9)).toBe('Well Focused');
    expect(formatCesLabel(60)).toBe('Well Focused');
    expect(formatCesLabel(59.9)).toBe('Getting There');
    expect(formatCesLabel(40)).toBe('Getting There');
    expect(formatCesLabel(39.9)).toBe('Room to Grow');
    expect(formatCesLabel(0)).toBe('Room to Grow');
  });

  it('never contains a digit — a raw score must never leak through the label', () => {
    for (const score of [0, 12.5, 39.9, 40, 59.9, 60, 79.9, 80, 100]) {
      expect(formatCesLabel(score)).not.toMatch(/\d/);
    }
  });

  it('returns "Unknown" instead of silently banding NaN or out-of-range input as the lowest band', () => {
    expect(formatCesLabel(NaN)).toBe('Unknown');
    expect(formatCesLabel(-10)).toBe('Unknown');
    expect(formatCesLabel(150)).toBe('Unknown');
  });
});

describe('formatTeachbackLabel — never returns a raw number, only a descriptive label', () => {
  it('returns "No teach-back this session" for null (zero attempts)', () => {
    expect(formatTeachbackLabel(null)).toBe('No teach-back this session');
  });

  it('bands: >=80 Strong grasp, >=60 Solid understanding, <60 Needs another look', () => {
    expect(formatTeachbackLabel(100)).toBe('Strong grasp');
    expect(formatTeachbackLabel(80)).toBe('Strong grasp');
    expect(formatTeachbackLabel(79.9)).toBe('Solid understanding');
    expect(formatTeachbackLabel(60)).toBe('Solid understanding');
    expect(formatTeachbackLabel(59.9)).toBe('Needs another look');
    expect(formatTeachbackLabel(0)).toBe('Needs another look');
  });

  it('never contains a digit for a non-null score — a raw score must never leak through the label', () => {
    for (const score of [0, 12.5, 59.9, 60, 79.9, 80, 100]) {
      expect(formatTeachbackLabel(score)).not.toMatch(/\d/);
    }
  });

  it('returns "Unknown" instead of silently banding NaN or out-of-range input as the lowest band', () => {
    expect(formatTeachbackLabel(NaN)).toBe('Unknown');
    expect(formatTeachbackLabel(-10)).toBe('Unknown');
    expect(formatTeachbackLabel(150)).toBe('Unknown');
  });
});
