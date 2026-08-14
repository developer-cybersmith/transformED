'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';
import { useLessonSocket } from '@/hooks/useLessonSocket';
import { trackEvent } from '@/lib/analytics';
import { completeSession, createSession } from '@/lib/assessment';
import type { LessonStatusResponse } from '@/services/upload.service';
import { AudioTimeline } from './AudioTimeline';
import { AvatarOverlay } from './AvatarOverlay';
import { CaptionOverlay } from './CaptionOverlay';
import { SlideRenderer } from './SlideRenderer';
import { PlayerControls } from './PlayerControls';
import { QuizOverlay } from './QuizOverlay';
import { TeachBackModal } from './TeachBackModal';
import { CheckingInTransition } from './CheckingInTransition';
import { TutorInterventionCard } from './TutorInterventionCard';
import { CESIndicator } from './CESIndicator';
import { AttentionConsentModal } from './AttentionConsentModal';
import { AttentionMonitor } from './AttentionMonitor';

interface PlayerProps {
  lesson: LessonPackage;
  /** Re-fetches the lesson from the backend (fresh signed media URLs) --
   *  called before retryAudio() so a Retry on an expired signed URL has a
   *  real chance of working instead of remounting the same dead URL (S2-33). */
  onRefetchLesson: () => Promise<LessonStatusResponse | null | undefined>;
}

// Matches the backend's own _TIER_LABELS dict exactly (apps/api/app/modules/
// assessment/service.py) -- do not invent different copy (S2-10).
// Exclude<..., undefined> — Story 2-25 (main) made LessonMetadata.tier optional
// in the frozen shared contract; a missing tier falls back to T2 below, same
// as an unrecognized one.
const TIER_LABELS: Record<Exclude<LessonPackage['metadata']['tier'], undefined>, string> = {
  T1: 'Full-Depth',
  T2: 'Standard',
  T3: 'Refresher',
};

// After this many manual retries on the same segment, surface extra guidance
// instead of silently letting the student hammer an identical failing request
// forever (review fix — no cap existed before this).
const REPEATED_FAILURE_RETRY_THRESHOLD = 3;

// Session creation (D18/Story 2-39) is a critical call — CLAUDE.md §14's
// failure-mode policy mandates 3 attempts for critical calls (2 for
// optional ones), with wait = 2^attempt + random(0,1) between them
// (review fix — a single transient network blip previously disabled quiz/
// teach-back for the entire session with no recovery).
const MAX_SESSION_CREATE_ATTEMPTS = 3;

// Default export required by next/dynamic
export default function Player({ lesson, onRefetchLesson }: PlayerProps) {
  const loadLesson = usePlayerStore((s) => s.loadLesson);
  const status = usePlayerStore((s) => s.status);
  const sessionId = usePlayerStore((s) => s.sessionId);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);
  const currentSlideId = usePlayerStore((s) => s.currentSlideId);
  const isBuffering = usePlayerStore((s) => s.isBuffering);
  const audioError = usePlayerStore((s) => s.audioError);
  const audioRetryCount = usePlayerStore((s) => s.audioRetryCount);
  const retryAudio = usePlayerStore((s) => s.retryAudio);
  // Guards against a rapid double-click firing two overlapping refetch+retry
  // cycles (review fix) -- audioError only clears once retryAudio() actually
  // runs at the end of the (possibly slow) refetch, so the button stays
  // visible/clickable for the whole in-flight window without this.
  const [isRetrying, setIsRetrying] = useState(false);

  // Re-fetches fresh signed media URLs before actually retrying (S2-33) --
  // retryAudio() alone just remounts the <audio> element with whatever src
  // is already in the store, which is the same expired URL if that's why it
  // failed. Refetch failures are swallowed here: worst case, retryAudio()
  // still remounts with the (possibly-still-stale) existing URL, matching
  // pre-S2-33 behavior rather than leaving Retry non-functional.
  async function handleRetryAudio() {
    if (isRetrying) return;
    setIsRetrying(true);
    try {
      const fresh = await onRefetchLesson();
      if (fresh?.content) {
        usePlayerStore.getState().refreshLessonMedia(fresh.content);
      }
    } catch {
      // Refetch failed -- fall through to retryAudio() with the existing lesson.
    } finally {
      setIsRetrying(false);
    }
    retryAudio();
  }

  // Mounts the lesson WebSocket for the duration of the session — previously
  // never called anywhere, so the socket never connected during a real lesson.
  useLessonSocket(sessionId || null);

  // Behavioral event instrumentation (analytics gap found in the 2026-07-29
  // Sprint 2 audit): the backend's session_events ingestion has been fully
  // built and tested since Dev 3's Sprint 2 work, but nothing in apps/web
  // ever called it. Tracks a tab_switch each time the student navigates away
  // from and back to this tab while a lesson is open.
  useEffect(() => {
    function handleVisibilityChange() {
      if (document.hidden) {
        // Read fresh from the store rather than closing over `segment` --
        // this effect intentionally mounts once for the whole session.
        const state = usePlayerStore.getState();
        const currentSegment = state.lesson?.segments[state.currentSegmentIndex] ?? null;
        trackEvent('tab_switch', { segment_id: currentSegment?.segment_id ?? null });
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Keyed on lesson_id (a stable primitive), NOT the lesson object reference
  // (review fix, S2-33): a retry-triggered refetch (handleRetryAudio ->
  // onRefetchLesson -> SWR mutate()) produces a NEW lesson object for the SAME
  // lesson_id -- if this effect depended on the `lesson` object itself, that
  // new reference alone would re-fire it and call loadLesson() again, silently
  // resetting currentSegmentIndex/audioPositionMs/quizFiredForSegment/status/
  // sessionId right after (or racing with) the deliberately-progress-preserving
  // refreshLessonMedia() call in handleRetryAudio -- defeating the entire point
  // of the retry-refetch flow. Depending on the id instead means React's own
  // dependency comparison already skips the effect for that case -- no ref
  // guard needed.
  //
  // A `loadedLessonIdRef`-style guard was tried here before and had to be
  // reverted (bug found via live testing, 2026-08-12): React 18 Strict Mode's
  // dev-only double-invoke (mount -> cleanup -> mount, same instance, same
  // ref) set the ref on the first invocation, which made the guard's
  // `ref.current === lesson.lesson_id` check block the SECOND (real,
  // uncancelled) invocation from ever calling mintSession -- so the *only*
  // mintSession call that ever ran was the first one, whose cleanup had
  // already flipped `cancelled` to true by the time its fetch resolved.
  // Net effect: sessionId stayed '' for the entire session in dev, silently --
  // no error, no log, nothing -- until confirmed live via a Playwright
  // session (WS never connected, [useAttentionMonitor] logged "dropping
  // attention signal -- no active socket connection" forever). Depending on
  // the primitive id removes the scenario the ref existed for, so the ref
  // itself is gone -- there is no longer anything for it to guard.
  const lessonId = lesson.lesson_id;
  useEffect(() => {
    loadLesson(lesson);
    // Must run after loadLesson's synchronous set() so state.lesson is
    // populated before restoreProgress validates the saved segmentIndex
    // against this lesson's actual bounds.
    usePlayerStore.getState().restoreProgress(lessonId);

    // Mints the real backend session (D18/Story 2-39) -- previously
    // loadLesson() invented sessionId: crypto.randomUUID() locally, which the
    // backend's ownership check correctly rejected (404 on every quiz/
    // teach-back submission, for every student, always). Fired once per
    // lesson mount -- every call mints a new attempt row server-side, which is
    // intentional (re-learning must produce a new session for CES history),
    // but calling it more than once per mount would mint extra, orphaned rows.
    //
    // `cancelled` guards against a stale response overwriting the (global,
    // shared) store's sessionId once this Player has unmounted (review fix,
    // matching useLessonSocket.ts's own pattern) -- PlayerLoader remounts a
    // fresh Player keyed on lesson_id, so a genuine lesson change unmounts
    // this instance entirely; without this guard, a slow response for a
    // lesson the student already navigated away from could resolve after
    // the new lesson's own (successful) session was set, silently
    // misattributing that lesson's quiz/teach-back submissions.
    let cancelled = false;
    let retryTimeoutId: ReturnType<typeof setTimeout> | undefined;

    async function mintSession(attempt: number) {
      try {
        const { session_id } = await createSession({ lesson_id: lessonId });
        if (cancelled) return;
        usePlayerStore.getState().setSessionId(session_id);
      } catch (err) {
        if (cancelled) return;
        if (attempt < MAX_SESSION_CREATE_ATTEMPTS) {
          const delayMs = (2 ** attempt + Math.random()) * 1000;
          retryTimeoutId = setTimeout(() => mintSession(attempt + 1), delayMs);
          return;
        }
        // Non-fatal: sessionId stays '' and playback is unaffected. Quiz/
        // teach-back submission will fail (existing catch blocks in
        // QuizOverlay/TeachBackModal already degrade gracefully), but a
        // failed session mint must not crash or block the player.
        console.error(
          `[Player] failed to create session after ${MAX_SESSION_CREATE_ATTEMPTS} attempts -- quiz/teach-back submission will fail:`,
          err
        );
      }
    }
    mintSession(1);

    return () => {
      cancelled = true;
      clearTimeout(retryTimeoutId);
    };
    // `lesson` itself is used inside (loadLesson(lesson)) but deliberately not
    // listed -- see the comment above `lessonId` for why this depends on the
    // id, not the object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId, loadLesson]);

  // Marks the session as ended so the session report's duration_minutes/
  // completed_at (assessment/service.py::get_session_report, which reads
  // sessions.ended_at) have a real value instead of silently staying
  // 0.0/None forever -- confirmed nothing anywhere ever wrote that column
  // (found via a live full-lesson playthrough, 2026-08-12). complete_session
  // is idempotent server-side (writes ended_at only once), so a duplicate
  // call here is harmless -- no ref guard needed. Non-fatal on failure: a
  // report field being wrong must never block the "Lesson complete" screen,
  // which is already rendered by the time this fires.
  useEffect(() => {
    if (status !== 'ENDED' || !sessionId) return;
    void completeSession(sessionId).catch(() => {
      // Swallowed on purpose -- see the comment above.
    });
  }, [status, sessionId]);

  const segment = lesson.segments[currentSegmentIndex] ?? null;

  return (
    <div className="flex-1 flex flex-col bg-white text-neutral-900 overflow-hidden">
      {/* AudioTimeline: hidden, drives audio playback + slide sync */}
      <AudioTimeline />

      {/* Slide area — all slides rendered simultaneously; only active is visible.
          min-h-0 is required here (D88): a flex item's default min-height is
          `auto`, meaning it will NOT shrink below its content's natural height
          even inside a flex-1 parent -- without this, tall slide content grows
          this container past the viewport instead of being clipped to it, and
          SlideRenderer's own overflow-y-auto never gets a bounded height to
          actually scroll within. */}
      <div className="relative flex-1 min-h-0">
        {/* Tier badge — persistent, visible regardless of playback state (S2-10).
            Not placed in the "before any slide is active" block below since
            currentSlideId is set almost immediately after mount in real use,
            leaving that block rarely visible. */}
        <div className="absolute top-3 left-3 z-10">
          <span className="px-3 py-1 rounded-full bg-white/90 backdrop-blur-sm border border-neutral-200 shadow-sm text-neutral-700 text-xs font-medium uppercase tracking-wide">
            {TIER_LABELS[lesson.metadata.tier ?? 'T2'] ?? TIER_LABELS.T2}
          </span>
        </div>

        {segment?.slides.map((slide) => (
          <SlideRenderer
            key={slide.slide_id}
            slide={slide}
            isActive={slide.slide_id === currentSlideId}
            jargon={segment.jargon}
          />
        ))}

        {/* Non-synced caption panel (D90) — shows the current segment's full
            narration script so students can read along; renders nothing when
            there's no script (mirrors SlideImage's own pattern). */}
        <CaptionOverlay script={segment?.narration.script ?? null} />

        {/* Lesson metadata shown before any slide is active */}
        {!currentSlideId && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6">
            <h2 className="font-serif text-xl font-semibold text-neutral-900">{lesson.metadata.title}</h2>
            <p className="text-neutral-500 text-sm">
              {lesson.metadata.total_segments} segments · ~{lesson.metadata.estimated_duration_mins} min
            </p>
          </div>
        )}

        {/* Quiz overlay — mounts over slide area when status === 'QUIZ' */}
        {status === 'QUIZ' && segment && (
          <QuizOverlay questions={segment.quiz} />
        )}

        {/* Teach-back modal — mounts after quiz when status === 'TEACH_BACK' */}
        {status === 'TEACH_BACK' && segment && (
          <TeachBackModal
            prompt={segment.teachback_prompt}
            segmentTitle={segment.title}
          />
        )}

        {/* Lesson complete screen */}
        {status === 'ENDED' && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-6 p-6 bg-white/95 backdrop-blur-sm">
            <div className="relative">
              <div className="absolute inset-0 bg-[var(--accent-secondary)]/20 rounded-full blur-xl animate-pulse" />
              <div className="relative w-20 h-20 bg-[var(--accent-secondary)]/10 text-4xl rounded-full flex items-center justify-center border border-[var(--accent-secondary)]/30">
                🎓
              </div>
            </div>
            <div className="text-center">
              <h2 className="font-serif text-neutral-900 text-2xl font-semibold mb-1">Lesson complete</h2>
              <p className="text-neutral-500 text-sm">{lesson.metadata.title}</p>
            </div>
            <div className="flex flex-col items-center gap-3">
              {sessionId && (
                <Link
                  href={`/reports/${sessionId}`}
                  className="px-6 py-2.5 rounded-full bg-[var(--accent-secondary)] text-primary
                             text-sm font-semibold hover:brightness-105 transition-all"
                >
                  View Session Report
                </Link>
              )}
              <Link
                href="/dashboard"
                className="text-neutral-500 hover:text-neutral-900 text-sm transition-colors"
              >
                Back to Dashboard
              </Link>
            </div>
          </div>
        )}

        {/* Buffering indicator — non-blocking, only while actively playing and stalled */}
        {isBuffering && status === 'PLAYING' && (
          <div
            className="absolute bottom-6 right-6 z-10 flex items-center gap-2 px-4 py-2 rounded-full bg-white/90 backdrop-blur-sm border border-neutral-200 shadow-sm text-neutral-700 text-xs"
            data-testid="audio-buffering"
          >
            <div className="w-3.5 h-3.5 border-2 border-neutral-200 border-t-[var(--accent-secondary)] rounded-full animate-spin" />
            Buffering...
          </div>
        )}

        {/* Playback error — visible during PLAYING/PAUSED/IDLE, offers a retry.
            Excluded from QUIZ/TEACH_BACK/ENDED (review fix): the narration audio's
            job for this segment is already done once the student has reached the
            quiz/teach-back/completion screen, so a stale or late-firing error must
            not block their progress there with a full-screen overlay. */}
        {audioError && status !== 'QUIZ' && status !== 'TEACH_BACK' && status !== 'ENDED' && (
          <div
            className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 p-6 bg-white/95 backdrop-blur-sm text-center"
            data-testid="audio-error"
          >
            <p className="text-neutral-600 text-sm">
              This segment&apos;s audio couldn&apos;t be played. Check your connection and try again.
            </p>
            {audioRetryCount >= REPEATED_FAILURE_RETRY_THRESHOLD && (
              <p className="text-neutral-400 text-xs max-w-xs">
                Still not working after several tries — this may take a moment to resolve, or try refreshing the page.
              </p>
            )}
            <button
              onClick={handleRetryAudio}
              disabled={isRetrying}
              className="px-5 py-2.5 rounded-full bg-[var(--accent-primary)] text-white text-sm font-medium hover:scale-105 transition-transform disabled:opacity-60 disabled:hover:scale-100"
            >
              {isRetrying ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        )}

        {/* Brief CHECKING_IN transition — layers on top of quiz/teach-back when it shows */}
        <CheckingInTransition />

        {/* Tutor intervention card (S3-03) — self-contained, non-blocking corner
            toast; never shows during TEACH_BACK (render-level guard inside). */}
        <TutorInterventionCard />

        {/* CES indicator (S3-04) — subtle, qualitative-only engagement dot; top-3 right-3, distinct from the tier badge (top-3 left-3). */}
        <CESIndicator />

        {/* Attention consent modal (S3-01) — self-contained, shown once before
            any camera code exists to gate (S3-02, not built yet). Suppressed
            during QUIZ/TEACH_BACK (review fix, same reasoning as audioError
            above): the consent read is async and can resolve after the
            player has already advanced past TEACHING, and this overlay must
            never block those screens. It reappears on the next opportunity
            since it hasn't been dismissed yet. */}
        {status !== 'QUIZ' && status !== 'TEACH_BACK' && <AttentionConsentModal />}

        {/* Attention monitor (S3-02) — renders nothing visible; self-contained,
            all consent/tutorState gating lives inside useAttentionMonitor. */}
        <AttentionMonitor />

        {/* Avatar intro/static/outro (S1-05) — self-contained, reads lesson +
            store state directly; renders nothing when no avatar fields are
            configured (every real lesson today, until Dev 1's pipeline
            wiring lands). */}
        <AvatarOverlay lesson={lesson} />
      </div>

      <PlayerControls />
    </div>
  );
}
