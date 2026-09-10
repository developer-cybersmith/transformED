import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import {
  CaptionOverlay,
  splitScriptIntoCaptionLines,
  activeCaptionLineIndex,
  activeCaptionLineIndexFromTimestamps,
  lineProgress,
  karaokeSpokenWordCount,
} from '@/components/player/CaptionOverlay';
import { usePlayerStore } from '@/stores/player.machine';
import type { CaptionLine } from '@hie/shared/types/lesson';

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

// ── activeCaptionLineIndexFromTimestamps ─────────────────────────────────────────

function line(text: string, start_ms: number, end_ms: number): CaptionLine {
  return { text, start_ms, end_ms };
}

describe('activeCaptionLineIndexFromTimestamps', () => {
  it('returns -1 for an empty lines array', () => {
    expect(activeCaptionLineIndexFromTimestamps([], 500)).toBe(-1);
  });

  it('clamps to line 0 when positionMs is before the first line start', () => {
    const lines = [line('a', 1000, 2000), line('b', 2000, 3000)];
    expect(activeCaptionLineIndexFromTimestamps(lines, 0)).toBe(0);
  });

  it('selects the line whose [start_ms, end_ms) window contains positionMs', () => {
    const lines = [line('a', 0, 1000), line('b', 1000, 2500), line('c', 2500, 4000)];
    expect(activeCaptionLineIndexFromTimestamps(lines, 0)).toBe(0);
    expect(activeCaptionLineIndexFromTimestamps(lines, 999)).toBe(0);
    expect(activeCaptionLineIndexFromTimestamps(lines, 1000)).toBe(1);
    expect(activeCaptionLineIndexFromTimestamps(lines, 2499)).toBe(1);
    expect(activeCaptionLineIndexFromTimestamps(lines, 2500)).toBe(2);
    expect(activeCaptionLineIndexFromTimestamps(lines, 3999)).toBe(2);
  });

  it('clamps to the last line once positionMs reaches or exceeds its end_ms', () => {
    const lines = [line('a', 0, 1000), line('b', 1000, 2000)];
    expect(activeCaptionLineIndexFromTimestamps(lines, 2000)).toBe(1);
    expect(activeCaptionLineIndexFromTimestamps(lines, 999999)).toBe(1);
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

// ── CaptionOverlay -- real server-provided caption_lines (Story 2-61 / BR-3) ─────

describe('CaptionOverlay — real caption_lines timestamp sync (BR-3)', () => {
  const realLines: CaptionLine[] = [
    line('Real line one from the server.', 0, 2000),
    line('Real line two from the server.', 2000, 5000),
  ];

  it('uses the real caption_lines text instead of a naive word-split of script', () => {
    usePlayerStore.setState({ audioDurationMs: 5000, audioPositionMs: 0 });
    render(
      <CaptionOverlay
        script="Completely different script text that would split differently."
        captionLines={realLines}
      />
    );

    expect(screen.getByText('Real line one from the server.')).not.toBeNull();
    expect(
      screen.queryByText(/Completely different script text/)
    ).toBeNull();
  });

  it('advances lines as audioPositionMs crosses each real end_ms boundary', () => {
    usePlayerStore.setState({ audioDurationMs: 5000, audioPositionMs: 0 });
    const { rerender } = render(<CaptionOverlay script="ignored" captionLines={realLines} />);
    expect(screen.getByText('Real line one from the server.')).not.toBeNull();

    act(() => {
      usePlayerStore.setState({ audioPositionMs: 2000 });
    });
    rerender(<CaptionOverlay script="ignored" captionLines={realLines} />);

    expect(screen.getByText('Real line two from the server.')).not.toBeNull();
    expect(screen.queryByText('Real line one from the server.')).toBeNull();
  });

  it('falls back to the proportional-estimate path when captionLines is undefined', () => {
    usePlayerStore.setState({ audioDurationMs: 0, audioPositionMs: 0 });
    const script = words(10).join(' ');
    render(<CaptionOverlay script={script} captionLines={undefined} />);

    expect(screen.getByText(script)).not.toBeNull();
  });

  it('falls back to the proportional-estimate path when captionLines is an empty array', () => {
    usePlayerStore.setState({ audioDurationMs: 0, audioPositionMs: 0 });
    const script = words(10).join(' ');
    render(<CaptionOverlay script={script} captionLines={[]} />);

    expect(screen.getByText(script)).not.toBeNull();
  });
});

// ── lineProgress (Story 2-62 / BR-4) ──────────────────────────────────────────────

describe('lineProgress', () => {
  it('clamps to 0 at or before the line start', () => {
    const l = line('a', 1000, 3000);
    expect(lineProgress(l, 1000)).toBe(0);
    expect(lineProgress(l, 500)).toBe(0);
  });

  it('clamps to 1 at or after the line end', () => {
    const l = line('a', 1000, 3000);
    expect(lineProgress(l, 3000)).toBe(1);
    expect(lineProgress(l, 9999)).toBe(1);
  });

  it('returns the elapsed fraction of the line window mid-line', () => {
    const l = line('a', 0, 2000);
    expect(lineProgress(l, 500)).toBe(0.25);
    expect(lineProgress(l, 1000)).toBe(0.5);
    expect(lineProgress(l, 1500)).toBe(0.75);
  });

  it('returns 1 for a zero-or-negative-span line', () => {
    expect(lineProgress(line('a', 1000, 1000), 1000)).toBe(1);
  });
});

// ── karaokeSpokenWordCount (Story 2-62 / BR-4) ────────────────────────────────────

describe('karaokeSpokenWordCount', () => {
  it('returns 0 for progress <= 0', () => {
    expect(karaokeSpokenWordCount('Real line one from the server.', 0)).toBe(0);
  });

  it('returns all words for progress >= 1', () => {
    expect(karaokeSpokenWordCount('Real line one from the server.', 1)).toBe(6);
  });

  it('returns 0 for empty text regardless of progress', () => {
    expect(karaokeSpokenWordCount('', 0.5)).toBe(0);
  });

  it('allocates words proportionally by character position at a mid progress', () => {
    // "Real line one from the server." is 30 chars; word end offsets are
    // Real=4, line=9, one=13, from=18, the=22, server.=30 (hand-computed).
    const text = 'Real line one from the server.';
    expect(karaokeSpokenWordCount(text, 0.1)).toBe(0); // target 3 < "Real" end (4)
    expect(karaokeSpokenWordCount(text, 0.2)).toBe(1); // target 6 -> "Real"
    expect(karaokeSpokenWordCount(text, 0.5)).toBe(3); // target 15 -> "Real line one"
    expect(karaokeSpokenWordCount(text, 0.9)).toBe(5); // target 27 -> "Real line one from the"
  });
});

// ── CaptionOverlay -- karaoke word-progress highlight (Story 2-62 / BR-4) ────────

describe('CaptionOverlay — karaoke-style word-progress highlight (BR-4)', () => {
  const realLines: CaptionLine[] = [line('Real line one from the server.', 0, 2000)];

  it('splits the active line into a spoken prefix and unspoken remainder mid-line', () => {
    usePlayerStore.setState({ audioDurationMs: 2000, audioPositionMs: 1000 }); // progress 0.5
    render(<CaptionOverlay script="ignored" captionLines={realLines} />);

    expect(screen.getByTestId('caption-spoken').textContent).toBe('Real line one');
    expect(screen.getByTestId('caption-unspoken').textContent).toBe('from the server.');
  });

  it('renders no spoken sub-span at the very start of a line (progress 0)', () => {
    usePlayerStore.setState({ audioDurationMs: 2000, audioPositionMs: 0 });
    render(<CaptionOverlay script="ignored" captionLines={realLines} />);

    expect(screen.queryByTestId('caption-spoken')).toBeNull();
    expect(screen.getByTestId('caption-unspoken').textContent).toBe(
      'Real line one from the server.'
    );
  });

  it('never renders spoken/unspoken sub-spans on the proportional-fallback path', () => {
    usePlayerStore.setState({ audioDurationMs: 10000, audioPositionMs: 5000 });
    const script = words(20).join(' ');
    render(<CaptionOverlay script={script} />);

    expect(screen.queryByTestId('caption-spoken')).toBeNull();
    expect(screen.queryByTestId('caption-unspoken')).toBeNull();
  });
});
