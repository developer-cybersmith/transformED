import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, act, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
import { AudioTimeline } from '@/components/player/AudioTimeline';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

// Origin must match test/setup.ts's NEXT_PUBLIC_SUPABASE_URL for
// parseSignedUrl's origin check (review finding) to accept this fixture.
const SIGNED_AUDIO_URL =
  'http://localhost:54321/storage/v1/object/sign/lesson-audio/lesson-1/seg-0.mp3?token=expired-token';

function loadLessonWithSignedAudioUrl() {
  const lesson = structuredClone(mockLessonPackage);
  lesson.segments[0].narration.audio_url = SIGNED_AUDIO_URL;
  usePlayerStore.getState().loadLesson(lesson);
}

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

  it('sets audioError(true) on the "error" event once the automatic re-sign attempt fails (Story 2-45 -- the attempt is async, so this no longer happens synchronously)', async () => {
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    const { container } = render(<AudioTimeline />);

    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(usePlayerStore.getState().audioError).toBe(true);
    });
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

describe('AudioTimeline — automatic per-asset re-sign (Story 2-45)', () => {
  it('swaps in the fresh signed URL, never sets audioError, and resumes playback (calls .play() again), when the automatic re-sign succeeds', async () => {
    loadLessonWithSignedAudioUrl();
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () =>
        HttpResponse.json({ signed_url: 'https://project.supabase.co/fresh-signed-mp3', expires_in: 3600 }),
      ),
    );

    const { container } = render(<AudioTimeline />);
    playMock.mockClear(); // drop the initial-mount play() call
    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(container.querySelector('audio')!.getAttribute('src')).toContain('fresh-signed-mp3');
    });
    expect(usePlayerStore.getState().audioError).toBe(false);
    // Review fix: the remounted <audio> element must actually be told to
    // play, not just receive the fresh src -- the play/pause effect's own
    // deps didn't previously include the resign, so this call never fired.
    expect(playMock).toHaveBeenCalled();
  });

  it('does not flip audioError for the new segment when a stale failed re-sign for an already-departed segment resolves late (race, review fix)', async () => {
    loadLessonWithSignedAudioUrl();
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });

    let resolveSignedUrl: (() => void) | null = null;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, async () => {
        await new Promise<void>((resolve) => {
          resolveSignedUrl = resolve;
        });
        return HttpResponse.json({ detail: 'Storage object not found' }, { status: 404 });
      }),
    );

    const { container } = render(<AudioTimeline />);
    fireEvent.error(container.querySelector('audio')!);

    // Wait for the re-sign request to actually be in flight.
    await waitFor(() => {
      expect(resolveSignedUrl).not.toBeNull();
    });

    // Student advances to segment 1 while segment 0's re-sign is still pending.
    // advanceSegment() resets audioError -- the healthy new segment starts clean.
    act(() => {
      usePlayerStore.getState().advanceSegment();
    });
    expect(usePlayerStore.getState().currentSegmentIndex).toBe(1);
    expect(usePlayerStore.getState().audioError).toBe(false);

    // Now let the stale re-sign for the abandoned segment 0 resolve with failure.
    await act(async () => {
      resolveSignedUrl?.();
      await new Promise((r) => setTimeout(r, 20));
    });

    // Segment 1 has nothing wrong with it -- audioError must stay false.
    expect(usePlayerStore.getState().audioError).toBe(false);
  });

  it('attempts the automatic re-sign at most once per segment — a later error on the same segment goes straight to audioError without a second network call', async () => {
    loadLessonWithSignedAudioUrl();
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    let signedUrlCallCount = 0;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        signedUrlCallCount += 1;
        return HttpResponse.json({ detail: 'Storage object not found' }, { status: 404 });
      }),
    );

    const { container } = render(<AudioTimeline />);
    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(usePlayerStore.getState().audioError).toBe(true);
    });
    expect(signedUrlCallCount).toBe(1);

    // Simulate the error firing again on the same (still-failing) segment,
    // independent of the manual Retry button, e.g. a second decode error.
    act(() => {
      usePlayerStore.getState().setAudioError(false);
    });
    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(usePlayerStore.getState().audioError).toBe(true);
    });
    expect(signedUrlCallCount).toBe(1);
  });

  it('does not attempt a re-sign for a segment whose audio_url is not a Supabase signed-url shape', async () => {
    // mockLessonPackage's default audio_url ('/What-Is-SQL-Injection.mp3') does
    // not match the signed-url shape parseSignedUrl expects.
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    let signedUrlCallCount = 0;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        signedUrlCallCount += 1;
        return HttpResponse.json({ signed_url: 'https://project.supabase.co/fresh', expires_in: 3600 });
      }),
    );

    const { container } = render(<AudioTimeline />);
    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(usePlayerStore.getState().audioError).toBe(true);
    });
    expect(signedUrlCallCount).toBe(0);
  });

  it('resets the attempt-guard on a manual retry, so a genuinely new asset for the same segment gets its own automatic attempt (AC4, review fix)', async () => {
    loadLessonWithSignedAudioUrl();
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    let signedUrlCallCount = 0;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        signedUrlCallCount += 1;
        return HttpResponse.json({ detail: 'Storage object not found' }, { status: 404 });
      }),
    );

    const { container } = render(<AudioTimeline />);
    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(usePlayerStore.getState().audioError).toBe(true);
    });
    expect(signedUrlCallCount).toBe(1);

    // Manual retry (Player.tsx's handleRetryAudio): a full-lesson refetch
    // delivers a fresh signed URL for the same segment_id, then retryAudio()
    // is called. Simulate the refetch by updating the store directly.
    act(() => {
      usePlayerStore.setState((state) => ({
        lesson: state.lesson
          ? {
              ...state.lesson,
              segments: state.lesson.segments.map((s, i) =>
                i === 0 ? { ...s, narration: { ...s.narration, audio_url: SIGNED_AUDIO_URL } } : s,
              ),
            }
          : state.lesson,
      }));
      usePlayerStore.getState().retryAudio();
    });
    expect(usePlayerStore.getState().audioError).toBe(false);

    // The "new" asset expires too -- without the fix, the guard would still
    // remember segment_id "seg-0" as already-attempted from before the
    // retry, and this would skip straight to audioError with no 2nd call.
    fireEvent.error(container.querySelector('audio')!);

    await waitFor(() => {
      expect(usePlayerStore.getState().audioError).toBe(true);
    });
    expect(signedUrlCallCount).toBe(2);
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
    utteranceCtor = vi.fn(function (this: { text: string; rate: number; onerror: unknown }, text: string) {
      this.text = text;
      this.rate = 1;
      this.onerror = null;
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

  // speak() is deferred by a setTimeout(0) after cancel() (review fix, to
  // avoid the same-tick cancel()+speak() race) -- fake timers + a 0ms
  // advance flush it, matching this file's existing convention for the
  // S2-33 virtual clock's own timer-driven behavior.
  function flushSpeakTimeout() {
    act(() => {
      vi.advanceTimersByTime(0);
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not throw and never speaks when window.speechSynthesis is unsupported (AC-2)', () => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    expect(() => render(<AudioTimeline />)).not.toThrow();
    flushSpeakTimeout();
    expect(usePlayerStore.getState().status).toBe('PLAYING');
  });

  it('does not throw and never speaks when speechSynthesis exists but SpeechSynthesisUtterance does not', () => {
    installSpeechSynthesis();
    (window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = undefined;
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    expect(() => render(<AudioTimeline />)).not.toThrow();
    flushSpeakTimeout();
    expect(speakMock).not.toHaveBeenCalled();
  });

  it('speaks the segment script via SpeechSynthesisUtterance on entering the virtual-clock branch while PLAYING (AC-1)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);
    flushSpeakTimeout();

    expect(utteranceCtor).toHaveBeenCalledWith(lesson.segments[0].narration.script);
    expect(speakMock).toHaveBeenCalledTimes(1);
  });

  it('cancel() happens before speak() is scheduled, and speak() does not fire in the same tick as cancel() (review fix)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);

    // Synchronously after mount, cancel() has fired but speak() has not --
    // it's deferred behind a setTimeout(0).
    expect(cancelMock).toHaveBeenCalled();
    expect(speakMock).not.toHaveBeenCalled();

    flushSpeakTimeout();

    expect(speakMock).toHaveBeenCalledTimes(1);
  });

  it('does not speak at all for a hasAudio segment (real audio present)', () => {
    installSpeechSynthesis();
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });

    render(<AudioTimeline />);
    flushSpeakTimeout();

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
    flushSpeakTimeout();

    const instance = utteranceCtor.mock.instances[0] as { rate: number };
    expect(instance.rate).toBe(1.5);
  });

  it('attaches an onerror handler so an engine failure never throws or surfaces (review fix)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);
    flushSpeakTimeout();

    const instance = utteranceCtor.mock.instances[0] as { onerror: unknown };
    expect(typeof instance.onerror).toBe('function');
    expect(() => (instance.onerror as () => void)()).not.toThrow();
  });

  it('calls speechSynthesis.pause() (not cancel()) when status leaves PLAYING (AC-4)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    flushSpeakTimeout();
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
    flushSpeakTimeout();

    act(() => {
      usePlayerStore.setState({ status: 'PAUSED' });
    });
    rerender(<AudioTimeline />);

    speakMock.mockClear();

    act(() => {
      usePlayerStore.setState({ status: 'PLAYING' });
    });
    rerender(<AudioTimeline />);
    flushSpeakTimeout();

    expect(resumeMock).toHaveBeenCalled();
    expect(speakMock).not.toHaveBeenCalled();
  });

  it('cancels the current utterance and speaks the new one when the segment changes (AC-6)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    flushSpeakTimeout();
    cancelMock.mockClear();

    act(() => {
      usePlayerStore.setState({ currentSegmentIndex: 1 });
    });
    rerender(<AudioTimeline />);
    flushSpeakTimeout();

    expect(cancelMock).toHaveBeenCalled();
    expect(utteranceCtor).toHaveBeenCalledWith(lesson.segments[1].narration.script);
  });

  it('cancels immediately when the segment changes even while PAUSED, not deferred to the next PLAYING transition (AC-6 review fix)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    flushSpeakTimeout();

    act(() => {
      usePlayerStore.setState({ status: 'PAUSED' });
    });
    rerender(<AudioTimeline />);
    cancelMock.mockClear();

    // Segment changes while PAUSED (e.g. a seek-driven segment change) --
    // cancel() must fire right away, not wait for a future PLAYING transition.
    act(() => {
      usePlayerStore.setState({ currentSegmentIndex: 1 });
    });
    rerender(<AudioTimeline />);

    expect(cancelMock).toHaveBeenCalled();
  });

  it('cancels the current utterance when leaving virtual-clock mode entirely (hasAudio becomes true)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    flushSpeakTimeout();
    cancelMock.mockClear();

    act(() => {
      usePlayerStore.getState().loadLesson(mockLessonPackage);
      usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0 });
    });
    rerender(<AudioTimeline />);

    expect(cancelMock).toHaveBeenCalled();
  });

  it('hard-cancels (not just pauses) when status reaches ENDED, since a finished lesson can never resume (review fix)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { rerender } = render(<AudioTimeline />);
    flushSpeakTimeout();
    cancelMock.mockClear();
    pauseSpeechMock.mockClear();

    act(() => {
      usePlayerStore.setState({ status: 'ENDED' });
    });
    rerender(<AudioTimeline />);

    expect(cancelMock).toHaveBeenCalled();
    expect(pauseSpeechMock).not.toHaveBeenCalled();
  });

  it('cancels any in-progress utterance on unmount (AC-7)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    const { unmount } = render(<AudioTimeline />);
    flushSpeakTimeout();
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
    flushSpeakTimeout();
    expect(speakMock).toHaveBeenCalledTimes(1);

    act(() => {
      usePlayerStore.setState({ isBuffering: true });
    });
    rerender(<AudioTimeline />);
    flushSpeakTimeout();

    expect(speakMock).toHaveBeenCalledTimes(1);
  });

  it('never advances audioPositionMs itself -- only the S2-33 virtual clock is the timing authority (AC-3)', () => {
    installSpeechSynthesis();
    const lesson = scriptOnlyLesson();
    usePlayerStore.getState().loadLesson(lesson);
    usePlayerStore.setState({ status: 'PLAYING', currentSegmentIndex: 0, quizFiredForSegment: new Set() });

    render(<AudioTimeline />);
    flushSpeakTimeout();

    expect(usePlayerStore.getState().audioPositionMs).toBe(0);
  });
});
