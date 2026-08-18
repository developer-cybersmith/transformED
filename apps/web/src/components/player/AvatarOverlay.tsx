'use client';

import { useEffect, useRef, useState } from 'react';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';

interface AvatarOverlayProps {
  lesson: LessonPackage;
}

// A video that stalls mid-network (never fires 'ended' or 'error') would
// otherwise block the intro/outro overlay forever -- this is the watchdog's
// upper bound on how long we wait before giving up (review fix).
const VIDEO_WATCHDOG_MS = 8_000;

// Story 1-5. Every field here is currently absent/null for every real lesson
// until Dev 1's pipeline wiring lands (package_builder_node doesn't populate
// them yet, see docs/proposals/avatar-fields-schema-change.md) -- this
// component's only currently-reachable behavior is "render nothing," which is
// deliberate and matches the original acceptance criteria: the player must
// never block or wait on any avatar asset.
export function AvatarOverlay({ lesson }: AvatarOverlayProps) {
  const status = usePlayerStore((s) => s.status);
  // Review fix: a genuine audio load failure (AudioTimeline's handleError,
  // which isn't gated on status) can fire while still IDLE. Without this
  // guard, the intro overlay (z-30) would sit on top of the audio-error
  // screen (z-20) and block its Retry button for the intro's entire
  // duration -- never permanently stuck, but a real window where recovering
  // from an unrelated failure is blocked by an unrelated feature.
  const audioError = usePlayerStore((s) => s.audioError);
  const introUrl = lesson.avatar_intro_url;
  const staticUrl = lesson.avatar_static_url;
  const outroUrl = lesson.avatar_outro_url;

  // Starts "done" when there's no URL at all, so a lesson with no avatar
  // fields configured never renders anything and never diverges from
  // pre-Story-1-5 behavior (AC-7).
  const [introDone, setIntroDone] = useState(!introUrl);
  const [outroDone, setOutroDone] = useState(!outroUrl);
  const [staticFailed, setStaticFailed] = useState(false);

  const introRef = useRef<HTMLVideoElement>(null);
  const outroRef = useRef<HTMLVideoElement>(null);

  // Autoplay while IDLE. If the browser blocks autoplay (no recent user
  // gesture) or the asset fails to load, don't strand the student waiting on
  // a video that will never play -- skip straight to the lesson exactly as if
  // no intro had been configured at all. A watchdog timeout covers the case
  // 'error' never fires at all (a network stall, not a definitive failure) --
  // onEnded/onError firing first clears it via the cleanup function.
  useEffect(() => {
    if (introDone || status !== 'IDLE') return;
    const video = introRef.current;
    if (!video) return;
    video.play().catch(() => {
      setIntroDone(true);
      usePlayerStore.getState().play();
    });
    const watchdog = setTimeout(() => {
      setIntroDone(true);
      usePlayerStore.getState().play();
    }, VIDEO_WATCHDOG_MS);
    return () => clearTimeout(watchdog);
  }, [introDone, status, introUrl]);

  // Same autoplay-block risk applies to the outro -- a bare `autoPlay`
  // attribute alone can silently never start (no onError fires for a
  // policy-blocked autoplay, only for a genuine load failure), which would
  // leave the outro overlay stuck in front of the "Lesson complete" screen
  // forever. Driving it the same way as the intro guarantees a way out, plus
  // the same network-stall watchdog.
  useEffect(() => {
    if (outroDone || status !== 'ENDED') return;
    const video = outroRef.current;
    if (!video) return;
    video.play().catch(() => setOutroDone(true));
    const watchdog = setTimeout(() => setOutroDone(true), VIDEO_WATCHDOG_MS);
    return () => clearTimeout(watchdog);
  }, [outroDone, status, outroUrl]);

  function handleIntroEnded() {
    setIntroDone(true);
    usePlayerStore.getState().play();
  }

  function handleOutroEnded() {
    setOutroDone(true);
  }

  return (
    <>
      {/* Intro -- full overlay while IDLE, until it finishes. Its own onEnded
          is what actually starts the lesson (play()), so this doubles as the
          "lesson start" trigger when configured -- the existing manual
          Play-button flow is untouched for the no-intro case (and remains
          usable as a de-facto skip during the intro, which is intentional --
          never trapping the student behind an unskippable video). Yields to
          a genuine audioError (see top-of-component note). */}
      {!introDone && status === 'IDLE' && introUrl && !audioError && (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center bg-black"
          data-testid="avatar-intro"
        >
          <video
            ref={introRef}
            src={introUrl}
            playsInline
            onEnded={handleIntroEnded}
            onError={handleIntroEnded}
            className="max-w-full max-h-full"
          />
        </div>
      )}

      {/* Static -- small persistent corner thumbnail during the actual lesson
          body only (not IDLE, not ENDED). Non-blocking, matches the
          buffering-indicator/tier-badge corner-overlay convention. Hides
          itself on a load failure (expired signed URL, 404) instead of
          leaving a broken-image icon pinned in the corner for the rest of
          the lesson (review fix). */}
      {staticUrl && !staticFailed && status !== 'IDLE' && status !== 'ENDED' && (
        <div
          className="absolute bottom-6 left-6 z-10 w-16 h-16 rounded-full overflow-hidden border-2 border-neutral-200 shadow-sm"
          data-testid="avatar-static"
        >
          <img
            src={staticUrl}
            alt=""
            className="w-full h-full object-cover animate-pulse"
            onError={() => setStaticFailed(true)}
          />
        </div>
      )}

      {/* Outro -- full overlay on top of Player's own ENDED "Lesson complete"
          screen until it finishes; that screen is already rendering
          underneath (Player.tsx's own status === 'ENDED' branch, untouched),
          this just visually covers it until the outro is done. */}
      {!outroDone && status === 'ENDED' && outroUrl && (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center bg-black"
          data-testid="avatar-outro"
        >
          <video
            ref={outroRef}
            src={outroUrl}
            playsInline
            onEnded={handleOutroEnded}
            onError={handleOutroEnded}
            className="max-w-full max-h-full"
          />
        </div>
      )}
    </>
  );
}
