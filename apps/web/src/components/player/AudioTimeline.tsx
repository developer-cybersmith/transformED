'use client';

import { useRef, useEffect, useState } from 'react';
import { usePlayerStore } from '@/stores/player.machine';
import { refreshSignedUrl } from '@/lib/media/refreshSignedUrl';

// Moved to lib/binarySearch.ts so stores/player.machine.ts (session-restore
// slide resolution) can use it without a component → store → component cycle.
// Re-exported here so existing imports from this module keep working.
import { binarySearchTimestamps } from '@/lib/binarySearch';
export { binarySearchTimestamps };

/**
 * Core audio-tick handler. Reads Zustand store via getState() to avoid stale closures
 * in the onTimeUpdate callback (fires at ~30 Hz). Exported for unit testing.
 */
export function processTimeUpdate(ms: number): void {
  const {
    status,
    lesson,
    currentSegmentIndex,
    currentSlideId,
    quizFiredForSegment,
    updateAudioPosition,
    setCurrentSlide,
    setTutorState,
    wsSendControl,
    enterQuiz,
  } = usePlayerStore.getState();

  if (!lesson) return;
  // Only process when actively playing — freeze during QUIZ, TEACH_BACK, PAUSED, IDLE, ENDED
  if (status !== 'PLAYING') return;

  const segment = lesson.segments[currentSegmentIndex];
  if (!segment) return;

  updateAudioPosition(ms);

  const { timestamps } = segment.narration;
  // Malformed/partial pipeline output — nothing to sync the slide/quiz boundary to.
  if (timestamps.length === 0) return;

  const idx = binarySearchTimestamps(timestamps, ms);
  const targetSlideId = timestamps[idx].slide_id;

  if (targetSlideId !== currentSlideId) {
    setCurrentSlide(targetSlideId);
  }

  // Segment boundary: fire quiz exactly once per forward traversal. Notify the
  // backend tutor FSM (segment_complete) and optimistically mirror CHECKING_IN
  // locally in the same tick — see CheckingInTransition / Dev Notes "Timing
  // constraint" for why this can't wait for the backend's state_change echo.
  const segmentEnd = timestamps.at(-1)!.end_ms;
  if (ms >= segmentEnd && !quizFiredForSegment.has(segment.segment_id)) {
    setTutorState('CHECKING_IN');
    wsSendControl?.({ type: 'segment_complete' });
    enterQuiz();
  }
}

/**
 * Bug fix: moves currentSlideId to whatever slide covers `ms`, independent
 * of playback status. A deliberate seek (the progress bar is usable while
 * PAUSED/IDLE too, per PlayerControls' canSeek) must move the visible slide
 * immediately -- processTimeUpdate's own per-tick sync is deliberately
 * gated on status === 'PLAYING' (so a paused lesson doesn't drift), which
 * previously meant a paused seek updated audioPositionMs optimistically
 * (player.machine.ts's requestSeek) but left the slide showing the pre-seek
 * position until the student resumed playback and a native 'timeupdate'
 * event eventually caught up. Never touches audioPositionMs/quiz state --
 * purely a visual slide sync. Exported for unit testing.
 */
export function syncSlideToPosition(ms: number): void {
  const { lesson, currentSegmentIndex, currentSlideId, setCurrentSlide } = usePlayerStore.getState();
  if (!lesson) return;
  const segment = lesson.segments[currentSegmentIndex];
  if (!segment) return;
  const { timestamps } = segment.narration;
  if (timestamps.length === 0) return;
  const idx = binarySearchTimestamps(timestamps, ms);
  const targetSlideId = timestamps[idx].slide_id;
  if (targetSlideId !== currentSlideId) {
    setCurrentSlide(targetSlideId);
  }
}

export function AudioTimeline() {
  const audioRef = useRef<HTMLAudioElement>(null);
  // Tracks which segment_id the current/last SpeechSynthesis utterance was
  // started for, so a status-only re-render (PAUSED -> PLAYING) resumes
  // instead of restarting narration from the beginning (S2-34 AC-5, AC-8).
  const spokenSegmentIdRef = useRef<string | null>(null);
  // Bug fix: the Web Speech API has no way to seek an in-progress utterance
  // to an arbitrary position -- unlike a real <audio> element, there's no
  // per-word/per-character timing to jump to. Without this, a seek moved the
  // slide/time (via processTimeUpdate/syncSlideToPosition) but the SPOKEN
  // narration just kept going from wherever it already was, completely
  // disconnected from what the student now sees. Bumped on every seek while
  // hasScript is true; the SpeechSynthesis effect below treats a nonce
  // change the same as a segment change (cancel + restart), which is the
  // best available approximation without word-level alignment data -- it
  // restarts from the beginning of the script rather than leaving stale,
  // desynced narration playing indefinitely.
  const [speechResyncNonce, setSpeechResyncNonce] = useState(0);

  // Story 2-45: a successful automatic per-asset re-sign overrides the
  // store's (expired) audio_url for exactly the segment it was resolved
  // for. Keyed by segment_id so a segment change naturally invalidates a
  // stale override without an explicit reset.
  const [resignedAudio, setResignedAudio] = useState<{ segmentId: string; url: string } | null>(null);
  // AC4: at most one automatic re-sign attempt per segment_id, ever -- a Set
  // keyed by segment_id needs no manual reset; a new segment_id is
  // automatically a fresh key. Persists across renders (ref, not state)
  // since attempting is a one-time side effect, not something to re-render on.
  const attemptedResignRef = useRef<Set<string>>(new Set());

  const status = usePlayerStore((s) => s.status);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);
  const seekRequestMs = usePlayerStore((s) => s.seekRequestMs);
  const playbackRate = usePlayerStore((s) => s.playbackRate);
  const audioRetryCount = usePlayerStore((s) => s.audioRetryCount);

  const segment = lesson?.segments[currentSegmentIndex] ?? null;
  // Story 2-45: prefer a successfully re-signed URL for THIS segment over
  // the store's (possibly expired) one -- never the reverse, so a resign
  // that resolved for a since-departed segment can't leak onto a new one.
  const effectiveAudioUrl =
    resignedAudio && segment && resignedAudio.segmentId === segment.segment_id
      ? resignedAudio.url
      : segment?.narration.audio_url;
  // Empty string is a real, reachable value now — a per-asset server-side
  // signing failure degrades just that one asset (Story 1-6/1-7), it doesn't
  // fail the whole lesson. There's nothing to play; don't attempt to.
  const hasAudio = Boolean(effectiveAudioUrl);
  // Story 2-31 (backend) recovers the real script into a segment that still
  // has no playable audio -- narration.script alone changes nothing on screen
  // unless something drives processTimeUpdate for it (S2-33's virtual clock,
  // below). Distinct from hasAudio === false && !hasScript, which still has
  // nothing to advance the segment at all and keeps the immediate-advance path.
  const hasScript = Boolean(segment?.narration.script?.trim());

  // Status drives audio — audio never drives status (S1-01 invariant).
  // Also re-runs on currentSegmentIndex: replaying a previously-quizzed segment
  // (seek backward, let it reach its natural end) advances the segment via
  // handleEnded without any status transition — status is PLAYING before and
  // after. The <audio> element remounts on the new segment_id key, so without
  // this dependency the new element would never receive a .play() call and
  // playback would silently freeze despite the UI still showing "playing".
  // Also re-runs on audioRetryCount (S2-26 review fix): retryAudio() remounts
  // the <audio> element via the same key mechanism, but status/currentSegmentIndex
  // don't change on a same-segment retry -- without this dependency, the fresh
  // element would sit loaded-and-paused forever with no play() call, which is
  // worse than the original stall (no error, no progress, no recovery).
  useEffect(() => {
    if (hasAudio) {
      const audio = audioRef.current;
      if (!audio) return;
      if (status === 'PLAYING') {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
      return;
    }
    if (hasScript) {
      // Virtual clock (S2-33, separate effect below) owns ticking/advancing
      // this segment -- nothing to do here.
      return;
    }
    // Nothing will ever load and there's no script either, so 'ended'/'timeupdate'
    // can never fire for this segment (review fix) -- drive the same
    // advance/quiz logic handleEnded uses immediately instead of leaving the
    // lesson stuck here forever.
    if (status === 'PLAYING') handleEnded();
    // resignedAudio's url (Story 2-45, review fix): a successful automatic
    // re-sign changes effectiveAudioUrl/hasAudio for a segment that was
    // already `hasAudio === true` before AND after (an expired URL is still
    // non-empty, so is a fresh one) -- neither of those already-covered
    // deps changes, so without this the remounted <audio> element would sit
    // loaded-and-paused forever with no .play() call, exactly the class of
    // bug this effect's own comment already documents for the retry case.
  }, [status, currentSegmentIndex, hasAudio, hasScript, audioRetryCount, resignedAudio?.url]);

  // Story 2-45 AC4 (review fix): a manual retry (Player.tsx's
  // handleRetryAudio, which always refetches the whole lesson -- fresh
  // signed URLs for every asset -- before calling retryAudio()) delivers a
  // genuinely new asset for the CURRENT segment_id. Clear that segment's
  // attempt-guard and any now-stale local override so, if this new asset
  // later expires too, it gets its own automatic re-sign attempt instead of
  // skipping straight to setAudioError because the old segment_id was
  // already marked "attempted" before the retry ever happened. Runs on
  // mount too (audioRetryCount starts at 0) -- harmless no-op there.
  useEffect(() => {
    if (!segment) return;
    attemptedResignRef.current.delete(segment.segment_id);
    // Deliberately synchronous -- this clears a stale one-off override in
    // response to a manual-retry EVENT (audioRetryCount changing), not on
    // every render; it is a no-op (bails via Object.is) on every render
    // where resignedAudio doesn't already belong to the current segment,
    // so the "cascading renders" concern the rule generally guards against
    // does not apply here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResignedAudio((prev) => (prev && prev.segmentId === segment.segment_id ? null : prev));
    // segment_id is the intended identity here, not the whole segment
    // object or effectiveAudioUrl -- this must run exactly once per manual
    // retry, not on every render that happens to recompute those.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioRetryCount]);

  // Virtual playback clock (S2-33): a segment with a recovered narration script
  // but no playable audio (Story 2-31's degrade path) still needs *something*
  // to drive processTimeUpdate's slide-sync/quiz-boundary logic, or the segment
  // looks instantly "ended" -- this is exactly the "quiz fires at 0:00" symptom
  // Dev 1's handoff (docs/dev2-narration-playback-handoff.md) traced here.
  // Ticks only while PLAYING; the effect's own cleanup (on segment/status change)
  // is what stops it. Uses a wall-clock delta (review fix) rather than a fixed
  // +100ms per tick -- setInterval is throttled in backgrounded tabs (browsers
  // commonly clamp to >=1000ms), and a fixed-per-tick advance would silently
  // run the virtual clock far slower than real elapsed time; multiplying by
  // playbackRate (review fix) keeps 1.5x/2x speed consistent with the real
  // <audio> path, which already applies it via audio.playbackRate.
  useEffect(() => {
    if (hasAudio || !hasScript) return;
    if (status !== 'PLAYING') return;

    let lastTick = Date.now();
    const interval = setInterval(() => {
      const state = usePlayerStore.getState();
      const now = Date.now();
      const elapsedMs = now - lastTick;
      lastTick = now;

      // React only clears this interval on its NEXT render after status
      // leaves PLAYING -- a leftover tick can still fire before that cleanup
      // runs (observable under vi.advanceTimersByTime's synchronous batch,
      // and possible in a real browser too). Bail immediately so a stale tick
      // can't run the post-quiz handleEnded() check below against a segment
      // that's no longer actually playing (review fix -- this exact gap
      // caused a phantom post-quiz tick to fire handleEnded() an extra time
      // and reset position/prematurely end the lesson).
      if (state.status !== 'PLAYING') return;

      // A pending seek is about to be applied authoritatively by the seek
      // effect below -- skip this tick so it can't race ahead of (or
      // duplicate) that application (review fix).
      if (state.seekRequestMs !== null) return;

      const seg = state.lesson?.segments[state.currentSegmentIndex];
      // Captured BEFORE processTimeUpdate() below, which may itself add this
      // segment_id to quizFiredForSegment on the very first boundary crossing --
      // distinguishes "already quizzed before this tick" (a replay, or resuming
      // PLAYING post-teach-back with nothing left to do) from "just got quizzed
      // by this tick" (the normal, first-time boundary case, already fully
      // handled by processTimeUpdate's own logic below).
      const alreadyQuizzed = seg ? state.quizFiredForSegment.has(seg.segment_id) : false;

      const nextMs = state.audioPositionMs + elapsedMs * state.playbackRate;
      processTimeUpdate(nextMs);

      // Review fix: without this, a segment that's already been quizzed (e.g.
      // exitTeachBack() resumes PLAYING on an already-quizzed last segment,
      // per its own "audio resumes... handleEnded fires endLesson when it
      // finishes" comment) never reaches ENDED -- there's no real 'ended'
      // event here to drive it, and processTimeUpdate's boundary check is a
      // no-op once quizFiredForSegment already has this segment. Safe to call
      // handleEnded() in this specific case regardless of last/non-last
      // segment: it only ever reaches advanceSegment()/endLesson() when the
      // quiz has already fired (AC-3's actual concern -- re-firing an
      // unquizzed segment's quiz -- cannot happen here).
      if (alreadyQuizzed && seg) {
        const segEnd = seg.narration.timestamps.at(-1)?.end_ms;
        if (segEnd !== undefined && nextMs >= segEnd) {
          handleEnded();
        }
      }
    }, 100);

    return () => clearInterval(interval);
  }, [hasAudio, hasScript, status, currentSegmentIndex]);

  // Sets a real total duration for the scrubber even without audio metadata to
  // load from -- timestamps always exist here (Story 2-19's estimation),
  // independent of play/pause state, so this doesn't need to be gated on status.
  // Explicitly resets to 0 rather than leaving a stale prior segment's duration
  // in place on the (defensive, shouldn't happen in practice) empty-timestamps
  // case (review fix).
  useEffect(() => {
    if (hasAudio || !hasScript || !segment) return;
    const { timestamps } = segment.narration;
    usePlayerStore.getState().setAudioDuration(
      timestamps.length > 0 ? timestamps.at(-1)!.end_ms : 0
    );
  }, [hasAudio, hasScript, segment]);

  // Browser SpeechSynthesis fallback (S2-34): the last tier of the TTS
  // fallback chain (CLAUDE.md: Sarvam Bulbul v2 -> Azure TTS -> Browser
  // Speech). Speaks the segment's script as supplementary audio for the
  // virtual-clock case (no audio, but a recovered script) -- this NEVER
  // drives processTimeUpdate or segment advancement; the S2-33 setInterval
  // clock above remains the sole timing authority. Mirrors <audio>
  // play/pause semantics: pause()/resume() on status transitions (not
  // cancel()+respeak, which would restart narration from the beginning),
  // cancel() on segment change or on leaving virtual-clock mode entirely.
  // Deps use segment_id (not the whole segment object) per AC-8 -- avoids
  // re-running on a re-render that recreates the segment object without
  // actually changing which segment is current (review fix).
  useEffect(() => {
    if (
      typeof window === 'undefined' ||
      !window.speechSynthesis ||
      typeof window.SpeechSynthesisUtterance !== 'function'
    ) {
      // Partial API support (has one but not the other) is treated the same
      // as fully unsupported -- silent no-op, never throws (review fix).
      return;
    }
    const synth = window.speechSynthesis;

    if (hasAudio || !hasScript || !segment) {
      synth.cancel();
      spokenSegmentIdRef.current = null;
      return;
    }

    // Bug fix: includes speechResyncNonce so a seek (which bumps the nonce
    // without changing segment_id) is treated the same as a new segment --
    // otherwise this comparison would never notice a seek at all, and the
    // narration would just keep speaking from wherever it already was.
    const speechKey = `${segment.segment_id}:${speechResyncNonce}`;

    // A new segment (or first entry into virtual-clock mode for it, or a
    // seek) -- stop whatever was playing/paused before, unconditional on
    // status. AC-6 requires cancel() on segment change regardless of
    // PLAYING/PAUSED/QUIZ etc.; previously this only happened lazily on the
    // next PLAYING transition, leaving a stale segment's utterance merely
    // paused indefinitely if the segment changed while not PLAYING (review
    // fix).
    if (spokenSegmentIdRef.current !== speechKey) {
      synth.cancel();
      spokenSegmentIdRef.current = null;
    }

    if (status === 'ENDED') {
      // Lesson is genuinely over -- nothing can ever transition back to
      // resume it, so free the speech queue immediately instead of leaving
      // it paused until unmount (review fix, user's explicit call).
      synth.cancel();
      spokenSegmentIdRef.current = null;
      return;
    }

    if (status !== 'PLAYING') {
      synth.pause();
      return;
    }

    if (spokenSegmentIdRef.current === speechKey) {
      synth.resume();
      return;
    }

    // Defer speak() by a tick after cancel() -- calling speak() in the same
    // synchronous stack as cancel() is a documented race in some engines
    // (notably Chrome) that can silently drop the new utterance (review
    // fix). Cleanup clears the pending call if the effect re-runs (e.g. a
    // rapid subsequent segment change) or unmounts before it fires.
    const script = segment.narration.script;
    const rate = usePlayerStore.getState().playbackRate;
    const timeoutId = window.setTimeout(() => {
      const utterance = new SpeechSynthesisUtterance(script);
      // Set once at speak-time, not kept live -- browser TTS engines don't
      // support changing an in-flight utterance's rate the way <audio>.playbackRate
      // does (S2-34 AC-9, known limitation).
      utterance.rate = rate;
      // Swallow engine failures (unavailable voice, permission, crash) --
      // this is supplementary audio only; a failure here must never surface
      // as an error or affect the lesson (review fix).
      utterance.onerror = () => {};
      synth.speak(utterance);
      spokenSegmentIdRef.current = speechKey;
    }, 0);

    return () => window.clearTimeout(timeoutId);
    // segment_id (not the whole segment object) is the intended dependency
    // per AC-8 -- re-running only when the segment actually changes, not on
    // a re-render that happens to recreate the segment object. speechResyncNonce
    // added for the seek bug fix above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segment?.segment_id, hasAudio, hasScript, status, speechResyncNonce]);

  // Stop any in-progress/paused utterance on unmount (S2-34 AC-7). Also
  // resets spokenSegmentIdRef -- without this, a React StrictMode dev
  // double-mount's cleanup pass cancels the just-started utterance while the
  // ref still claims it was spoken, so the second mount silently calls a
  // no-op resume() instead of a fresh speak() (review fix).
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      spokenSegmentIdRef.current = null;
    };
  }, []);

  // Apply pending seek from the store then clear it. In virtual-clock mode
  // there's no real <audio> element to set .currentTime on -- absorb the seek
  // by applying it directly via processTimeUpdate instead (S2-33 AC-5).
  useEffect(() => {
    if (seekRequestMs === null) return;
    // Bug fix: sync the slide immediately, regardless of status -- see
    // syncSlideToPosition's own doc comment for why processTimeUpdate alone
    // (below, or via the next native 'timeupdate' event) isn't enough.
    syncSlideToPosition(seekRequestMs);
    if (hasAudio) {
      const audio = audioRef.current;
      if (audio) {
        audio.currentTime = seekRequestMs / 1000;
      }
    } else if (hasScript) {
      processTimeUpdate(seekRequestMs);
      // Bug fix: the Web Speech API can't be seeked to an arbitrary position
      // (see speechResyncNonce's own doc comment) -- bump the nonce so the
      // SpeechSynthesis effect below restarts the utterance instead of
      // leaving it speaking on, completely disconnected from the new
      // slide/time position. Deliberately synchronous -- this responds to a
      // seek EVENT (seekRequestMs changing), not a per-render loop; same
      // justification as this file's other eslint-disabled setState-in-effect
      // calls.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSpeechResyncNonce((n) => n + 1);
    }
    usePlayerStore.getState().clearSeekRequest();
  }, [seekRequestMs, hasAudio, hasScript]);

  // Keep audio playback rate in sync
  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.playbackRate = playbackRate;
  }, [playbackRate]);

  function handleLoadedMetadata(e: React.SyntheticEvent<HTMLAudioElement>) {
    const durationMs = e.currentTarget.duration * 1000;
    usePlayerStore.getState().setAudioDuration(isFinite(durationMs) ? durationMs : 0);
    // Re-apply playback rate after src change resets it
    e.currentTarget.playbackRate = usePlayerStore.getState().playbackRate;
  }

  function handleTimeUpdate(e: React.SyntheticEvent<HTMLAudioElement>) {
    processTimeUpdate(e.currentTarget.currentTime * 1000);
  }

  function handleWaiting() {
    usePlayerStore.getState().setBuffering(true);
  }

  function handlePlaying() {
    usePlayerStore.getState().setBuffering(false);
  }

  function handleCanPlay() {
    usePlayerStore.getState().setBuffering(false);
  }

  function handleError() {
    // Only a real mid-load/decode failure on a segment that DID have a src —
    // the hasAudio === false degrade path never renders a src attribute at
    // all, so this can't double-fire alongside that fallback.
    //
    // Story 2-45 AC2/AC4: before surfacing audioError (which hands recovery
    // to the manual Retry button), try exactly one automatic per-asset
    // re-sign -- most failures here are a signed URL that expired while the
    // student was away, not a genuinely dead asset. `void` — this is a
    // fire-and-forget attempt from a synchronous DOM event; a slow/failed
    // resign still falls through to setAudioError below in the same tick.
    const seg = segment;
    const expiredUrl = seg?.narration.audio_url;
    if (seg && expiredUrl && !attemptedResignRef.current.has(seg.segment_id)) {
      attemptedResignRef.current.add(seg.segment_id);
      void refreshSignedUrl(expiredUrl).then((fresh) => {
        if (fresh) {
          // Currency is enforced downstream by effectiveAudioUrl's own
          // segmentId comparison -- a resign that resolves after the
          // student has moved on is simply never read.
          setResignedAudio({ segmentId: seg.segment_id, url: fresh });
          return;
        }
        // Re-sign itself failed (network/404/malformed) -- fall through to
        // the existing, already-surfaced manual-recovery path, but ONLY if
        // `seg` is still the current segment (review fix). Without this
        // check, a resign that started for segment N and resolves late --
        // after the student has advanced past N, manually retried N (a
        // fresh attempt is now in flight for N under a clean slate), or a
        // different lesson has loaded entirely -- would flip audioError to
        // true for whatever segment/lesson is current NOW, even though it
        // has nothing wrong with it.
        const current = usePlayerStore.getState();
        const stillCurrent = current.lesson?.segments[current.currentSegmentIndex]?.segment_id === seg.segment_id;
        if (stillCurrent) {
          current.setAudioError(true);
        }
      });
      return;
    }
    usePlayerStore.getState().setAudioError(true);
  }

  function handleEnded() {
    const {
      lesson: l,
      currentSegmentIndex: idx,
      quizFiredForSegment,
      endLesson,
      advanceSegment,
      setTutorState,
      wsSendControl,
      enterQuiz,
    } = usePlayerStore.getState();
    if (!l) return;
    const segment = l.segments[idx];
    const isLast = idx >= l.segments.length - 1;

    if (isLast) {
      // Last segment: end the lesson (quiz boundary detection handles quiz first if not yet fired)
      if (segment && !quizFiredForSegment.has(segment.segment_id)) {
        setTutorState('CHECKING_IN');
        wsSendControl?.({ type: 'segment_complete' });
        enterQuiz(); // audio ended before quiz fired (very short audio or tight timing)
      } else {
        wsSendControl?.({ type: 'lesson_complete' });
        endLesson();
      }
    } else {
      // Non-last segment: if quiz already fired (student sought back and replayed), advance
      if (segment && quizFiredForSegment.has(segment.segment_id)) {
        advanceSegment();
      }
      // If quiz hasn't fired yet, processTimeUpdate's boundary check should have caught it.
      // If the audio ended before hitting the boundary, fire the quiz now.
      else if (segment) {
        setTutorState('CHECKING_IN');
        wsSendControl?.({ type: 'segment_complete' });
        enterQuiz();
      }
    }
  }

  if (!segment) return null;

  return (
    // key includes audioRetryCount — forces remount on segment change AND on
    // retryAudio(), resetting src + currentTime so a failed load is re-attempted
    // from scratch rather than relying on the browser's own retry behavior.
    // Also includes resignedAudio's url (Story 2-45): a successful automatic
    // re-sign needs the same forced remount, not a bare src mutation, for
    // the browser to reliably start loading the fresh URL.
    <audio
      key={`${segment.segment_id}-${audioRetryCount}-${resignedAudio?.url ?? 'orig'}`}
      ref={audioRef}
      src={hasAudio ? effectiveAudioUrl : undefined}
      preload="metadata"
      onLoadedMetadata={handleLoadedMetadata}
      onTimeUpdate={handleTimeUpdate}
      onEnded={handleEnded}
      onWaiting={handleWaiting}
      onPlaying={handlePlaying}
      onCanPlay={handleCanPlay}
      onError={handleError}
      aria-label={`Narration: ${segment.title}`}
      className="sr-only"
    />
  );
}
