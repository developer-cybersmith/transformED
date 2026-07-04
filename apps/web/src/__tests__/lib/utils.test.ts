import { describe, it, expect } from 'vitest';
import { formatTimeAgo } from '@/lib/utils';

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
});
