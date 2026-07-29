'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';
import { useLessonSocket } from '@/hooks/useLessonSocket';
import type { LessonStatusResponse } from '@/services/upload.service';
import { AudioTimeline } from './AudioTimeline';
import { SlideRenderer } from './SlideRenderer';
import { PlayerControls } from './PlayerControls';
import { QuizOverlay } from './QuizOverlay';
import { TeachBackModal } from './TeachBackModal';
import { CheckingInTransition } from './CheckingInTransition';

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

  // Re-fetches fresh signed media URLs before actually retrying (S2-33) --
  // retryAudio() alone just remounts the <audio> element with whatever src
  // is already in the store, which is the same expired URL if that's why it
  // failed. Refetch failures are swallowed here: worst case, retryAudio()
  // still remounts with the (possibly-still-stale) existing URL, matching
  // pre-S2-33 behavior rather than leaving Retry non-functional.
  async function handleRetryAudio() {
    try {
      const fresh = await onRefetchLesson();
      if (fresh?.content) {
        usePlayerStore.getState().refreshLessonMedia(fresh.content);
      }
    } catch {
      // Refetch failed -- fall through to retryAudio() with the existing lesson.
    }
    retryAudio();
  }

  // Mounts the lesson WebSocket for the duration of the session — previously
  // never called anywhere, so the socket never connected during a real lesson.
  useLessonSocket(sessionId || null);

  useEffect(() => {
    loadLesson(lesson);
    // Must run after loadLesson's synchronous set() so state.lesson is
    // populated before restoreProgress validates the saved segmentIndex
    // against this lesson's actual bounds.
    usePlayerStore.getState().restoreProgress(lesson.lesson_id);
  }, [lesson, loadLesson]);

  const segment = lesson.segments[currentSegmentIndex] ?? null;

  return (
    <div className="flex-1 flex flex-col bg-primary-dark text-white overflow-hidden">
      {/* AudioTimeline: hidden, drives audio playback + slide sync */}
      <AudioTimeline />

      {/* Slide area — all slides rendered simultaneously; only active is visible */}
      <div className="relative flex-1">
        {/* Tier badge — persistent, visible regardless of playback state (S2-10).
            Not placed in the "before any slide is active" block below since
            currentSlideId is set almost immediately after mount in real use,
            leaving that block rarely visible. */}
        <div className="absolute top-3 left-3 z-10">
          <span className="px-3 py-1 rounded-full bg-black/40 backdrop-blur-sm text-neutral-200 text-xs font-medium uppercase tracking-wide">
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

        {/* Lesson metadata shown before any slide is active */}
        {!currentSlideId && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6">
            <h2 className="font-serif text-xl font-semibold">{lesson.metadata.title}</h2>
            <p className="text-neutral-400 text-sm">
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
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-6 p-6 bg-primary-dark/95 backdrop-blur-sm">
            <div className="relative">
              <div className="absolute inset-0 bg-[var(--accent-secondary)]/20 rounded-full blur-xl animate-pulse" />
              <div className="relative w-20 h-20 bg-[var(--accent-secondary)]/10 text-4xl rounded-full flex items-center justify-center border border-[var(--accent-secondary)]/30">
                🎓
              </div>
            </div>
            <div className="text-center">
              <h2 className="font-serif text-white text-2xl font-semibold mb-1">Lesson complete</h2>
              <p className="text-neutral-400 text-sm">{lesson.metadata.title}</p>
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
                className="text-neutral-400 hover:text-white text-sm transition-colors"
              >
                Back to Dashboard
              </Link>
            </div>
          </div>
        )}

        {/* Buffering indicator — non-blocking, only while actively playing and stalled */}
        {isBuffering && status === 'PLAYING' && (
          <div
            className="absolute bottom-6 right-6 z-10 flex items-center gap-2 px-4 py-2 rounded-full bg-black/60 backdrop-blur-sm text-neutral-200 text-xs"
            data-testid="audio-buffering"
          >
            <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
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
            className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 p-6 bg-primary-dark/95 backdrop-blur-sm text-center"
            data-testid="audio-error"
          >
            <p className="text-neutral-300 text-sm">
              This segment&apos;s audio couldn&apos;t be played. Check your connection and try again.
            </p>
            {audioRetryCount >= REPEATED_FAILURE_RETRY_THRESHOLD && (
              <p className="text-neutral-500 text-xs max-w-xs">
                Still not working after several tries — this may take a moment to resolve, or try refreshing the page.
              </p>
            )}
            <button
              onClick={handleRetryAudio}
              className="px-5 py-2.5 rounded-full bg-[var(--accent-primary)] text-white text-sm font-medium hover:scale-105 transition-transform"
            >
              Retry
            </button>
          </div>
        )}

        {/* Brief CHECKING_IN transition — layers on top of quiz/teach-back when it shows */}
        <CheckingInTransition />
      </div>

      <PlayerControls />
    </div>
  );
}
