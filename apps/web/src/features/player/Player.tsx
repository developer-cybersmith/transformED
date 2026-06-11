'use client'

import { useEffect, useState } from 'react'
import type { LessonPackage } from '@transformed/shared/types/lesson'
import type { TutorInterveneMessage, StateChangeMessage } from '@transformed/shared/types/ws'
import { usePlayer } from './usePlayer'
import { SlideRenderer } from './SlideRenderer'
import { AvatarOverlay } from './AvatarOverlay'
import { AudioTimeline } from './AudioTimeline'
import { TutorInterventionCard } from '../tutor/TutorInterventionCard'
import { QuizModal } from '../quiz/QuizModal'
import { TeachBackModal } from '../teachback/TeachBackModal'
import { ConsentModal } from '../attention/ConsentModal'
import { useMediaPipe } from '../attention/useMediaPipe'
import { wsClient } from '@/lib/websocket/client'
import { createClient } from '@/lib/supabase/client'
import { usePlayerStore } from './player.machine'

interface PlayerProps {
  lesson: LessonPackage
}

export function Player({ lesson }: PlayerProps) {
  const {
    play,
    pause,
    seek,
    nextSegment,
    prevSegment,
    currentSegmentIndex,
    currentSlideIndex,
    currentTimeMs,
    playerState,
    tutorState,
    activeIntervention,
    isQuizOpen,
    isTeachBackOpen,
    audioDurationMs,
  } = usePlayer(lesson)

  const { handleTutorIntervention, acknowledgeIntervention, closeQuiz, closeTeachBack, setTutorState } =
    usePlayerStore()

  // ── Attention / MediaPipe ───────────────────────────────────────────────
  const [attentionConsent, setAttentionConsent] = useState<boolean | null>(null)
  const [showConsentModal, setShowConsentModal] = useState(true)
  const { startCapture, stopCapture, latestSignals } = useMediaPipe()

  // ── WebSocket session ───────────────────────────────────────────────────
  const [sessionId] = useState(() => `${lesson.lesson_id}-${Date.now()}`)

  useEffect(() => {
    const supabase = createClient()
    supabase.auth.getSession().then(({ data }) => {
      const token = data.session?.access_token ?? ''
      wsClient.connect(sessionId, token)
    })

    wsClient.onMessage((msg) => {
      if (msg.type === 'tutor_intervene') {
        const m = msg as TutorInterveneMessage
        handleTutorIntervention(m.payload.type, m.payload.message, m.payload.action)
      }
      if (msg.type === 'state_change') {
        const m = msg as StateChangeMessage
        setTutorState(m.payload.to_state)
      }
    })

    return () => {
      wsClient.disconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // ── Send attention signals every 5 seconds ────────────────────────────
  useEffect(() => {
    if (!attentionConsent) return

    const interval = setInterval(() => {
      if (latestSignals) {
        wsClient.send({
          type: 'attention_signal',
          payload: {
            session_id: sessionId,
            quiz_accuracy: null,
            teachback_score: null,
            behavioral_score: latestSignals.behavioral_score,
            head_pose_score: latestSignals.head_pose_score,
            blink_rate: latestSignals.blink_rate,
          },
        })
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [attentionConsent, latestSignals, sessionId])

  // ── Consent handlers ────────────────────────────────────────────────────
  function handleConsentAllow() {
    setAttentionConsent(true)
    setShowConsentModal(false)
    startCapture()
  }

  function handleConsentDecline() {
    setAttentionConsent(false)
    setShowConsentModal(false)
  }

  // ── Derived data ────────────────────────────────────────────────────────
  const segment = lesson.segments[currentSegmentIndex]
  const slide = segment?.slides[currentSlideIndex] ?? segment?.slides[0]

  if (!segment || !slide) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900 text-white">
        <p className="text-slate-400">Loading lesson…</p>
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-slate-900 text-white">
      {/* Consent modal — shown once on mount */}
      {showConsentModal && (
        <ConsentModal onAllow={handleConsentAllow} onDecline={handleConsentDecline} />
      )}

      {/* Main player layout */}
      <div className="flex flex-1 gap-4 overflow-hidden p-4">
        {/* Left — slide */}
        <div className="flex-1 overflow-y-auto">
          <SlideRenderer slide={slide} jargon={segment.jargon} />
        </div>

        {/* Right — avatar */}
        <div className="w-52 flex-shrink-0">
          <AvatarOverlay playerState={playerState} segmentTitle={segment.title} />
        </div>
      </div>

      {/* Bottom — audio timeline */}
      <div className="flex-shrink-0 p-4 pt-0">
        <AudioTimeline
          playerState={playerState}
          currentTimeMs={currentTimeMs}
          durationMs={audioDurationMs}
          onPlay={play}
          onPause={pause}
          onSeek={seek}
          onNext={nextSegment}
          onPrev={prevSegment}
          segmentIndex={currentSegmentIndex}
          totalSegments={lesson.segments.length}
        />
      </div>

      {/* Tutor intervention card overlay */}
      {tutorState === 'INTERVENING' && activeIntervention && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <TutorInterventionCard
            type={activeIntervention.type}
            message={activeIntervention.message}
            onAcknowledge={acknowledgeIntervention}
          />
        </div>
      )}

      {/* Quiz modal */}
      {isQuizOpen && (
        <QuizModal
          questions={segment.quiz}
          onComplete={closeQuiz}
        />
      )}

      {/* Teach-back modal */}
      {isTeachBackOpen && (
        <TeachBackModal
          segmentId={segment.segment_id}
          prompt={segment.teachback_prompt}
          onComplete={closeTeachBack}
        />
      )}
    </div>
  )
}
