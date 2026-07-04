import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { AudioTimeline } from '@/components/player/AudioTimeline';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

let playMock: ReturnType<typeof vi.fn>;
let pauseMock: ReturnType<typeof vi.fn>;
const originalPlay = window.HTMLMediaElement.prototype.play;
const originalPause = window.HTMLMediaElement.prototype.pause;

beforeEach(() => {
  playMock = vi.fn().mockResolvedValue(undefined);
  pauseMock = vi.fn();
  window.HTMLMediaElement.prototype.play = playMock;
  window.HTMLMediaElement.prototype.pause = pauseMock;

  usePlayerStore.getState().loadLesson(mockLessonPackage);
});

afterEach(() => {
  window.HTMLMediaElement.prototype.play = originalPlay;
  window.HTMLMediaElement.prototype.pause = originalPause;
});

describe('AudioTimeline — play/pause follows status', () => {
  it('calls .play() on mount when status is PLAYING', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });

    render(<AudioTimeline />);

    expect(playMock).toHaveBeenCalled();
  });

  it('calls .pause() when status is not PLAYING', () => {
    usePlayerStore.setState({ status: 'PAUSED', currentSegmentIndex: 0 });

    render(<AudioTimeline />);

    expect(pauseMock).toHaveBeenCalled();
    expect(playMock).not.toHaveBeenCalled();
  });
});

describe('AudioTimeline — segment replay does not freeze playback', () => {
  it('calls .play() on the new segment\'s audio element when a replayed (already-quizzed) segment ends', () => {
    // Simulates: student sought backward into seg_0 (quiz already fired for it this
    // session) and lets the audio play through to its natural end again.
    usePlayerStore.setState({
      status: 'PLAYING',
      currentSegmentIndex: 0,
      quizFiredForSegment: new Set(['seg_0']),
    });

    const { container } = render(<AudioTimeline />);

    const firstAudio = container.querySelector('audio');
    expect(firstAudio?.getAttribute('aria-label')).toBe('Narration: What is SQL Injection?');

    playMock.mockClear(); // drop the initial-mount play() call — only care about post-transition calls

    fireEvent.ended(firstAudio!);

    // The state layer is not the bug: advanceSegment() correctly fires and status
    // never changes (it was PLAYING before and after) — this is exactly the
    // condition the play/pause effect's dependency array must also react to.
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(1);
    expect(usePlayerStore.getState().status).toBe('PLAYING');

    const secondAudio = container.querySelector('audio');
    expect(secondAudio).not.toBe(firstAudio); // key change forced a remount
    expect(secondAudio?.getAttribute('aria-label')).toBe(
      'Narration: Bypassing Authentication & Prevention'
    );

    // The new <audio> element must actually be told to play — without this, the
    // student sees a "playing" UI over silent, frozen audio with no recovery
    // short of manually toggling pause/play.
    expect(playMock).toHaveBeenCalled();
  });

  it('does NOT advance (or need to play a new element) when replaying a segment whose quiz has not fired yet', () => {
    // Normal forward-flow case: quiz boundary detection in processTimeUpdate is
    // responsible here, not handleEnded — handleEnded should only fire the quiz,
    // not silently skip past it.
    usePlayerStore.setState({
      status: 'PLAYING',
      currentSegmentIndex: 0,
      quizFiredForSegment: new Set(),
    });

    const { container } = render(<AudioTimeline />);
    const audio = container.querySelector('audio');

    fireEvent.ended(audio!);

    expect(usePlayerStore.getState().currentSegmentIndex).toBe(0);
    expect(usePlayerStore.getState().status).toBe('QUIZ');
  });
});
