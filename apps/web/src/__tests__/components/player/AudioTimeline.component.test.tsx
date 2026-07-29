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

  it('advances faster than wall-clock time when playbackRate > 1 (review fix)', () => {
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
      usePlayerStore.setState({
        status: 'PLAYING',
        currentSegmentIndex: 0,
        quizFiredForSegment: new Set(),
        playbackRate: 2.0,
      });

      render(<AudioTimeline />);

      act(() => {
        vi.advanceTimersByTime(1000); // 1s of wall-clock time
      });

      // At 2x, ~1000ms of wall-clock elapsed should advance position by ~2000ms.
      expect(usePlayerStore.getState().audioPositionMs).toBeGreaterThanOrEqual(1900);
    } finally {
      vi.useRealTimers();
    }
  });

  it('transitions to ENDED when PLAYING resumes on an already-quizzed last segment (review fix -- exitTeachBack() resuming a script-only last segment previously had no way to ever reach ENDED)', () => {
    vi.useFakeTimers();
    try {
      const singleSegmentLesson = {
        ...mockLessonPackage,
        segments: [
          { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        ],
      };
      usePlayerStore.getState().loadLesson(singleSegmentLesson);
      const segEnd = singleSegmentLesson.segments[0].narration.timestamps.at(-1)!.end_ms;
      // Simulates exitTeachBack()'s resumption: quiz already fired for this
      // (last) segment, status set back to PLAYING, position already at the
      // segment's end (where the quiz originally fired).
      usePlayerStore.setState({
        status: 'PLAYING',
        currentSegmentIndex: 0,
        quizFiredForSegment: new Set(['seg_0']),
        audioPositionMs: segEnd,
      });

      render(<AudioTimeline />);

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(usePlayerStore.getState().status).toBe('ENDED');
    } finally {
      vi.useRealTimers();
    }
  });

  it('resets audioDuration to 0 for a script-only segment with no timestamps (defensive, review fix)', () => {
    const lessonWithNoTimestamps = {
      ...mockLessonPackage,
      segments: [
        {
          ...mockLessonPackage.segments[0],
          narration: { ...mockLessonPackage.segments[0].narration, audio_url: '', timestamps: [] },
        },
        ...mockLessonPackage.segments.slice(1),
      ],
    };
    usePlayerStore.getState().loadLesson(lessonWithNoTimestamps);
    usePlayerStore.setState({ status: 'PAUSED', currentSegmentIndex: 0, audioDurationMs: 99999 });

    render(<AudioTimeline />);

    expect(usePlayerStore.getState().audioDurationMs).toBe(0);
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

describe('AudioTimeline — SpeechSynthesis fallback (S2-34)', () => {
  const originalSpeechSynthesis = window.speechSynthesis;
  const originalUtterance = (window as unknown as { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance;

  let speakMock: ReturnType<typeof vi.fn>;
  let cancelMock: ReturnType<typeof vi.fn>;
  let pauseSpeechMock: ReturnType<typeof vi.fn>;
  let resumeMock: ReturnType<typeof vi.fn>;
  let utteranceCtor: ReturnType<typeof vi.fn>;

  function installSpeechSynthesis() {
    speakMock = vi.fn();
    cancelMock = vi.fn();
    pauseSpeechMock = vi.fn();
    resumeMock = vi.fn();
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: { speak: speakMock, cancel: cancelMock, pause: pauseSpeechMock, resume: resumeMock },
    });
    utteranceCtor = vi.fn(function (this: { text: string; rate: number }, text: string) {
      this.text = text;
      this.rate = 1;
    });
    (window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = utteranceCtor;
  }

  afterEach(() => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: originalSpeechSynthesis });
    (window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = originalUtterance;
  });

  function scriptOnlyLesson() {
    return {
      ...mockLessonPackage,
      segments: [
        { ...mockLessonPackage.segments[0], narration: { ...mockLessonPackage.segments[0].narration, audio_url: '' } },
        { ...mockLessonPackage.segments[1], narration: { ...mockLessonPackage.segments[1].narration, audio_url: '' } },
      ],
    };
  }

  it('does not throw and never speaks when window.speechSynthesis is unsupported (AC-2)', () => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    expect(() => render(<AudioTimeline />)).not.toThrow();
    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  it('speaks the segment script via SpeechSynthesisUtterance on entering the virtual-clock branch while PLAYING (AC-1)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);

    expect(utteranceCtor).toHaveBeenCalledWith(lesson.segments[0].narration.script);
    expect(speakMock).toHaveBeenCalledTimes(1);
  });

  it('does not speak at all for a hasAudio segment (real audio present)', () => {
    installSpeechSynthesis();
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });

    render(<AudioTimeline />);

    expect(speakMock).not.toHaveBeenCalled();
  });

  it('sets utterance.rate from the store playbackRate at speak time, not updated live afterward (AC-9)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({
      status: 'PLAYING',
      currentSegmentIndex: 0,
      quizFiredForSegment: new Set(),
      playbackRate: 1.5,
    });

    render(<AudioTimeline />);

    const instance = utteranceCtor.mock.instances[0] as { rate: number };
    expect(instance.rate).toBe(1.5);
  });

  it('calls speechSynthesis.pause() (not cancel()) when status leaves PLAYING (AC-4)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    // Clear the mount's own pre-speak cancel() (a harmless, unconditional
    // safety call before the very first utterance) so this only asserts on
    // calls made by the status transition itself.
    speakMock.mockClear();
    cancelMock.mockClear();

    act(() => {
      usePlayerStore.setState({ status: 'PAUSED' });
    });
    rerender(<AudioTimeline />);

    expect(pauseSpeechMock).toHaveBeenCalled();
    expect(cancelMock).not.toHaveBeenCalled();
    expect(speakMock).not.toHaveBeenCalled();
  });

  it('calls speechSynthesis.resume() (not a fresh speak()) when PLAYING resumes for the same segment (AC-5)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);

    act(() => {
      usePlayerStore.setState({ status: 'PAUSED' });
    });
    rerender(<AudioTimeline />);

    speakMock.mockClear();

    act(() => {
      usePlayerStore.setState({ status: 'PLAYING' });
    });
    rerender(<AudioTimeline />);

    expect(resumeMock).toHaveBeenCalled();
    expect(speakMock).not.toHaveBeenCalled();
  });

  it('cancels the current utterance and speaks the new one when the segment changes (AC-6)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    cancelMock.mockClear();

    act(() => {
      usePlayerStore.setState({ currentSegmentIndex: 1 });
    });
    rerender(<AudioTimeline />);

    expect(cancelMock).toHaveBeenCalled();
    expect(utteranceCtor).toHaveBeenCalledWith(lesson.segments[1].narration.script);
  });

  it('cancels the current utterance when leaving virtual-clock mode entirely (hasAudio becomes true)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    cancelMock.mockClear();

    act(() => {
      usePlayerStore.getState().loadLesson(mockLessonPackage);
      usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    });
    rerender(<AudioTimeline />);

    expect(cancelMock).toHaveBeenCalled();
  });

  it('cancels any in-progress utterance on unmount (AC-7)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { unmount } = render(<AudioTimeline />);
    cancelMock.mockClear();

    unmount();

    expect(cancelMock).toHaveBeenCalled();
  });

  it('does not double-speak on an unrelated re-render (AC-8)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    expect(speakMock).toHaveBeenCalledTimes(1);

    act(() => {
      usePlayerStore.setState({ isBuffering: true });
    });
    rerender(<AudioTimeline />);

    expect(speakMock).toHaveBeenCalledTimes(1);
  });

  it('never advances audioPositionMs itself -- only the S2-33 virtual clock is the timing authority (AC-3)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);

    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });
});
