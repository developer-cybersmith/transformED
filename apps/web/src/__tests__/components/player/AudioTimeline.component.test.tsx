import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, act } from '@testing-library/react';
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
  usePlayerStore.setState({ wsSendControl: null });
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

describe('AudioTimeline — audio_url can be "" (per-asset signing failure degrade, S1-7)', () => {
  it('does not set a src, and does not attempt to play, when the segment has no audio_url', () => {
    const lessonWithMissingAudio = {
      ...mockLessonPackage,
      segments: [
        { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithMissingAudio);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });

    const { container } = render(<AudioTimeline />);
    const audio = container.querySelector('audio');

    expect(audio).not.toBeNull();
    expect(audio?.getAttribute('src')).toBeNull();
    expect(playMock).not.toHaveBeenCalled();
  });

  it('does not permanently freeze on a segment with no audio AND no script -- advances/quizzes immediately since ended/timeupdate can never fire (review fix; re-pointed for S2-33 -- see below for the has-script case)', () => {
    const lessonWithNothing = {
      ...mockLessonPackage,
      segments: [
        {
          ...mockLessonPackage.segments[0],
          narration: { ...mockLessonPackage.segments[0].narration, audio_url: '', script: '' },
        },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithNothing);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);

    // No audio ever loads for this segment and there's no script either, so
    // nothing will ever fire 'ended' -- the component must drive the
    // quiz/advance logic itself rather than wait for an event that can never come.
    expect(usePlayerStore.getState().status).toBe('QUIZ');
  });
});

describe('AudioTimeline — virtual playback clock (S2-33): no audio, but a recovered script', () => {
  it('does NOT synchronously reach QUIZ on mount -- the clock advances over time, not immediately (this is the exact regression the backend fix alone did not close)', () => {
    const lessonWithScriptOnly = {
      ...mockLessonPackage,
      segments: [
        { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithScriptOnly);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);

    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  it('ticks processTimeUpdate every 100ms while PLAYING, eventually firing the quiz at the real segment boundary', () => {
    vi.useFakeTimers();
    try {
      const lessonWithScriptOnly = {
        ...mockLessonPackage,
        segments: [
          { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
          ...mockLessonPackage.segments.slice(1),
        ],
      };
      usePlayerStore.getState().loadLesson(lessonWithScriptOnly);
      usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

      render(<AudioTimeline />);

      // seg_0 (mockLessonPackage) ends at 92000ms -- advance the fake clock past it.
      act(() => {
        vi.advanceTimersByTime(93000);
      });

      expect(usePlayerStore.getState().status).toBe('QUIZ');
      expect(usePlayerStore.getState().audioPositionMs).toBeGreaterThanOrEqual(92000);
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops ticking (does not keep advancing audioPositionMs) once status leaves PLAYING', () => {
    vi.useFakeTimers();
    try {
      const lessonWithScriptOnly = {
        ...mockLessonPackage,
        segments: [
          { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
          ...mockLessonPackage.segments.slice(1),
        ],
      };
      usePlayerStore.getState().loadLesson(lessonWithScriptOnly);
      usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

      const { rerender } = render(<AudioTimeline />);

      act(() => {
        vi.advanceTimersByTime(500);
      });
      const positionWhilePlaying = usePlayerStore.getState().audioPositionMs;
      expect(positionWhilePlaying).toBeGreaterThan(0);

      act(() => {
        usePlayerStore.setState({ status: 'PAUSED' });
      });
      rerender(<AudioTimeline />);

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(usePlayerStore.getState().audioPositionMs).toBe(positionWhilePlaying);
    } finally {
      vi.useRealTimers();
    }
  });

  it('sets audioDuration from the segment\'s last timestamp, independent of PLAYING status', () => {
    const lessonWithScriptOnly = {
      ...mockLessonPackage,
      segments: [
        { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithScriptOnly);
    usePlayerStore.setState({ status: 'PAUSED', currentSegmentIndex: 0 });

    render(<AudioTimeline />);

    const expectedEndMs = lessonWithScriptOnly.segments[0].narration.timestamps.at(-1)!.end_ms;
    expect(usePlayerStore.getState().audioDurationMs).toBe(expectedEndMs);
  });

  it('absorbs a pending seek via processTimeUpdate instead of setting .currentTime on a nonexistent real element', () => {
    // status must be PLAYING for the seek to actually move currentSlideId --
    // processTimeUpdate itself no-ops otherwise (same guard the real-audio
    // path is already subject to: a seek while paused updates audioPositionMs
    // immediately via requestSeek(), but slide sync only catches up once
    // playback resumes).
    const lessonWithScriptOnly = {
      ...mockLessonPackage,
      segments: [
        { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithScriptOnly);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);

    act(() => {
      usePlayerStore.getState().requestSeek(40000); // into seg_0's sl_0_1 range (35000-92000)
    });

    expect(usePlayerStore.getState().currentSlideId).toBe('sl_0_1');
    expect(usePlayerStore.getState().seekRequestMs).toBeNull();
  });

  it('never calls handleEnded-driven advanceSegment/endLesson from the clock itself -- only the boundary check in processTimeUpdate fires the quiz', () => {
    vi.useFakeTimers();
    try {
      // Single-segment lesson: if the clock incorrectly called handleEnded()
      // in addition to processTimeUpdate's own boundary firing, this would
      // double-advance past the quiz straight to ENDED.
      const singleSegmentLesson = {
        ...mockLessonPackage,
        segments: [
          { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ],
      };
      usePlayerStore.getState().loadLesson(singleSegmentLesson);
      usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

      render(<AudioTimeline />);

      act(() => {
        vi.advanceTimersByTime(93000 + 500); // well past the segment boundary
      });

      expect(usePlayerStore.getState().status).toBe('QUIZ');
    } finally {
      vi.useRealTimers();
    }
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

describe('AudioTimeline — buffering / error / retry (S2-26)', () => {
  it('sets isBuffering(true) on the "waiting" event', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    const { container } = render(<AudioTimeline />);

    fireEvent.waiting(container.querySelector('audio')!);

    expect(usePlayerStore.getState().isBuffering).toBe(true);
  });

  it('clears isBuffering on the "playing" event', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, isBuffering: true });
    const { container } = render(<AudioTimeline />);

    fireEvent.playing(container.querySelector('audio')!);

    expect(usePlayerStore.getState().isBuffering).toBe(false);
  });

  it('clears isBuffering on the "canplay" event', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, isBuffering: true });
    const { container } = render(<AudioTimeline />);

    fireEvent.canPlay(container.querySelector('audio')!);

    expect(usePlayerStore.getState().isBuffering).toBe(false);
  });

  it('sets audioError(true) on the "error" event', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    const { container } = render(<AudioTimeline />);

    fireEvent.error(container.querySelector('audio')!);

    expect(usePlayerStore.getState().audioError).toBe(true);
  });

  it('does not attach an error-triggering src at all for a hasAudio === false segment (degrade path unaffected)', () => {
    const lessonWithMissingAudio = {
      ...mockLessonPackage,
      segments: [
        { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithMissingAudio);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });

    const { container } = render(<AudioTimeline />);
    const audio = container.querySelector('audio');

    expect(audio?.getAttribute('src')).toBeNull();
    expect(usePlayerStore.getState().audioError).toBe(false);
  });

  it('remounts the <audio> element (new element identity) when audioRetryCount changes', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, audioRetryCount: 0 });
    const { container, rerender } = render(<AudioTimeline />);
    const firstAudio = container.querySelector('audio');

    act(() => {
      usePlayerStore.setState({ audioRetryCount: 1 });
    });
    rerender(<AudioTimeline />);
    const secondAudio = container.querySelector('audio');

    expect(secondAudio).not.toBe(firstAudio);
  });

  it('calls .play() again on the fresh element after a same-segment retry (review fix — regression: retry cleared the error but never resumed playback)', () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, audioRetryCount: 0, audioError: true });
    const { rerender } = render(<AudioTimeline />);
    playMock.mockClear(); // drop the initial-mount play() call

    act(() => {
      usePlayerStore.getState().retryAudio();
    });
    rerender(<AudioTimeline />);

    expect(playMock).toHaveBeenCalled();
  });
});

describe('AudioTimeline — handleEnded sends segment_complete (S2-06 AC2/AC6)', () => {
  it('non-last segment, quiz not yet fired: sends segment_complete and sets tutorState CHECKING_IN', () => {
    const sendControl = vi.fn();
    usePlayerStore.setState({
      status: 'PLAYING',
      currentSegmentIndex: 0,
      quizFiredForSegment: new Set(),
      wsSendControl: sendControl,
    });

    const { container } = render(<AudioTimeline />);
    fireEvent.ended(container.querySelector('audio')!);

    expect(sendControl).toHaveBeenCalledTimes(1);
    expect(sendControl).toHaveBeenCalledWith({ type: 'segment_complete' });
    expect(usePlayerStore.getState().tutorState).toBe('CHECKING_IN');
  });

  it('last segment, quiz not yet fired: sends segment_complete and sets tutorState CHECKING_IN', () => {
    const sendControl = vi.fn();
    const lastIndex = mockLessonPackage.segments.length - 1;
    usePlayerStore.setState({
      status: 'PLAYING',
      currentSegmentIndex: lastIndex,
      quizFiredForSegment: new Set(),
      wsSendControl: sendControl,
    });

    const { container } = render(<AudioTimeline />);
    fireEvent.ended(container.querySelector('audio')!);

    expect(sendControl).toHaveBeenCalledTimes(1);
    expect(sendControl).toHaveBeenCalledWith({ type: 'segment_complete' });
    expect(usePlayerStore.getState().tutorState).toBe('CHECKING_IN');
  });

  it('does NOT send segment_complete again when replaying an already-quizzed segment (advanceSegment branch)', () => {
    const sendControl = vi.fn();
    usePlayerStore.setState({
      status: 'PLAYING',
      currentSegmentIndex: 0,
      quizFiredForSegment: new Set(['seg_0']),
      wsSendControl: sendControl,
    });

    const { container } = render(<AudioTimeline />);
    fireEvent.ended(container.querySelector('audio')!);

    expect(sendControl).not.toHaveBeenCalled();
  });
});
