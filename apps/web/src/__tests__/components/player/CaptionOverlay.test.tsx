import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import {
  CaptionOverlay,
  splitScriptIntoCaptionLines,
  activeCaptionLineIndex,
} from '@/components/player/CaptionOverlay';
import { usePlayerStore } from '@/stores/player.machine';

function words(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `word${i}`);
}

beforeEach(() => {
  // CaptionOverlay now reads audioPositionMs/audioDurationMs from the store
  // (review redesign, 2026-08-17) -- reset both so every test starts from a
  // known, deterministic state regardless of what a previous test left behind.
  usePlayerStore.setState({ audioPositionMs: 0, audioDurationMs: 0 });
});

// ── splitScriptIntoCaptionLines ────────────────────────────────────────────────

describe('splitScriptIntoCaptionLines', () => {
  it('returns [] for an empty or whitespace-only script', () => {
    expect(splitScriptIntoCaptionLines('')).toEqual([]);
    expect(splitScriptIntoCaptionLines('   ')).toEqual([]);
  });

  it('returns a single line for a script shorter than one line', () => {
    expect(splitScriptIntoCaptionLines('Hello world')).toEqual(['Hello world']);
  });

  it('splits a longer script into ~10-word lines, last line carrying the remainder', () => {
    const script = words(25).join(' ');
    const lines = splitScriptIntoCaptionLines(script);
    expect(lines).toHaveLength(3);
    expect(lines[0].split(' ')).toHaveLength(10);
    expect(lines[1].split(' ')).toHaveLength(10);
    expect(lines[2].split(' ')).toHaveLength(5);
    // Round-tripping the lines back together must reproduce every word, in order.
    expect(lines.join(' ')).toBe(script);
  });

  it('collapses irregular whitespace between words', () => {
    expect(splitScriptIntoCaptionLines('Hello   world\n\ttoday')).toEqual(['Hello world today']);
  });
});

// ── activeCaptionLineIndex ──────────────────────────────────────────────────────

describe('activeCaptionLineIndex', () => {
  it('returns -1 for an empty lines array', () => {
    expect(activeCaptionLineIndex([], 5000, 10000)).toBe(-1);
  });

  it('defaults to line 0 when total duration is not yet known (<= 0) -- duration not loaded yet', () => {
    expect(activeCaptionLineIndex(['a', 'bb', 'ccc'], 5000, 0)).toBe(0);
    expect(activeCaptionLineIndex(['a', 'bb', 'ccc'], 5000, -1)).toBe(0);
  });

  it('picks the line whose proportional time window contains the position, split evenly for equal-length lines', () => {
    const lines = ['aaaa', 'bbbb', 'cccc']; // all 4 chars -> 1/3 of totalMs each
    const totalMs = 9000; // 3000ms per line
    expect(activeCaptionLineIndex(lines, 0, totalMs)).toBe(0);
    expect(activeCaptionLineIndex(lines, 2999, totalMs)).toBe(0);
    expect(activeCaptionLineIndex(lines, 3000, totalMs)).toBe(1);
    expect(activeCaptionLineIndex(lines, 5999, totalMs)).toBe(1);
    expect(activeCaptionLineIndex(lines, 6000, totalMs)).toBe(2);
    expect(activeCaptionLineIndex(lines, 8999, totalMs)).toBe(2);
  });

  it('weights a longer line with proportionally more time than a shorter one', () => {
    const lines = ['a', 'aaaaaaaaa']; // 1 char vs 9 chars of 10 total
    const totalMs = 10000; // line 0 gets 1000ms, line 1 gets the remaining 9000ms
    expect(activeCaptionLineIndex(lines, 999, totalMs)).toBe(0);
    expect(activeCaptionLineIndex(lines, 1001, totalMs)).toBe(1);
  });

  it('clamps to the last line once position reaches or exceeds the total duration', () => {
    const lines = ['aaaa', 'bbbb'];
    expect(activeCaptionLineIndex(lines, 1000, 1000)).toBe(1);
    expect(activeCaptionLineIndex(lines, 999999, 1000)).toBe(1);
  });
});

// ── CaptionOverlay component ────────────────────────────────────────────────────

describe('CaptionOverlay — content', () => {
  it('renders the narration script text when it fits in a single line', () => {
    render(<CaptionOverlay script="Welcome to the tutorial. Today we cover SQL injection." />);
    expect(
      screen.getByText(/Welcome to the tutorial\. Today we cover SQL injection\./)
    ).toBeDefined();
  });

  it('renders the caption panel container when a script is present', () => {
    render(<CaptionOverlay script="Some narration text." />);
    expect(screen.getByTestId('caption-overlay')).toBeDefined();
  });

  it('review fix: the caption panel must accept pointer events so its own overflow-y-auto scroll actually works', () => {
    // Regression for a real, browser-verified bug: `pointer-events-none`
    // alongside `overflow-y-auto` blocks ALL wheel/mouse-driven scrolling on
    // the element (no keyboard path either -- this is a plain non-focusable
    // div). jsdom can't compute real scrollHeight/clientHeight or CSS cascade
    // effects, so this asserts the class directly -- the only thing that
    // actually caused the bug. Kept as a defensive guard even though lines
    // are now short enough that overflow should rarely trigger.
    render(<CaptionOverlay script="Some narration text." />);
    const overlay = screen.getByTestId('caption-overlay');
    expect(overlay.className).not.toMatch(/pointer-events-none/);
    expect(overlay.hasAttribute('data-lenis-prevent')).toBe(true);
  });
});

describe('CaptionOverlay — render nothing when there is nothing to show', () => {
  it('renders nothing when script is null', () => {
    const { container } = render(<CaptionOverlay script={null} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('caption-overlay')).toBeNull();
  });

  it('renders nothing when script is an empty string', () => {
    const { container } = render(<CaptionOverlay script="" />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('caption-overlay')).toBeNull();
  });
});

describe('CaptionOverlay — YouTube/Netflix-style one-line-at-a-time captions (review redesign)', () => {
  it('shows only the FIRST line initially, not the whole script', () => {
    const script = words(25).join(' ');
    render(<CaptionOverlay script={script} />);

    expect(screen.getByText(words(10).join(' '))).not.toBeNull();
    expect(screen.queryByText(words(25).slice(10, 20).join(' '))).toBeNull();
    expect(screen.queryByText(script)).toBeNull();
  });

  it('defaults to the first line while audioDurationMs is not yet known, even with a long script', () => {
    usePlayerStore.setState({ audioDurationMs: 0, audioPositionMs: 4000 });
    const script = words(25).join(' ');

    render(<CaptionOverlay script={script} />);

    expect(screen.getByText(words(10).join(' '))).not.toBeNull();
  });

  it('advances to a later line as audioPositionMs increases, once duration is known', () => {
    const script = words(20).join(' '); // 2 lines of 10 words each
    usePlayerStore.setState({ audioDurationMs: 10000, audioPositionMs: 0 });

    const { rerender } = render(<CaptionOverlay script={script} />);
    expect(screen.getByText(words(10).join(' '))).not.toBeNull();

    act(() => {
      usePlayerStore.setState({ audioPositionMs: 9000 });
    });
    rerender(<CaptionOverlay script={script} />);

    expect(screen.getByText(words(20).slice(10, 20).join(' '))).not.toBeNull();
    expect(screen.queryByText(words(10).join(' '))).toBeNull();
  });

  it('never shows two lines at once', () => {
    const script = words(30).join(' '); // 3 lines
    usePlayerStore.setState({ audioDurationMs: 30000, audioPositionMs: 15000 });

    render(<CaptionOverlay script={script} />);

    expect(screen.getAllByTestId('caption-overlay')).toHaveLength(1);
  });
});
