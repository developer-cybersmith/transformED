'use client'

import { useEffect, useRef, useCallback } from 'react'
import { usePlayerStore } from './player.machine'
import type { LessonPackage } from '@transformed/shared/types/lesson'

export interface UsePlayerReturn {
  play: () => void
  pause: () => void
  seek: (ms: number) => void
  nextSegment: () => void
  prevSegment: () => void
  currentSegmentIndex: number
  currentSlideIndex: number
  currentTimeMs: number
  playerState: ReturnType<typeof usePlayerStore.getState>['playerState']
  tutorState: ReturnType<typeof usePlayerStore.getState>['tutorState']
  activeIntervention: ReturnType<typeof usePlayerStore.getState>['activeIntervention']
  isQuizOpen: boolean
  isTeachBackOpen: boolean
  audioDurationMs: number
}

export function usePlayer(lesson: LessonPackage): UsePlayerReturn {
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const store = usePlayerStore()
  const {
    currentSegmentIndex,
    currentSlideIndex,
    currentTimeMs,
    playerState,
    tutorState,
    activeIntervention,
    isQuizOpen,
    isTeachBackOpen,
    loadLesson,
    handleTimeUpdate,
    handleSegmentEnd,
  } = store

  const audioDurationRef = useRef<number>(0)

  // ── Load lesson into store on mount ────────────────────────────────────
  useEffect(() => {
    loadLesson(lesson)
  }, [lesson, loadLesson])

  // ── Create and manage the Audio element ────────────────────────────────
  useEffect(() => {
    const audio = new Audio()
    audioRef.current = audio

    // Polling via timeupdate (fires ~4x/s in browsers)
    const onTimeUpdate = () => {
      handleTimeUpdate(audio.currentTime * 1000)
    }

    const onEnded = () => {
      handleSegmentEnd()
    }

    const onWaiting = () => {
      usePlayerStore.setState({ playerState: 'BUFFERING' })
    }

    const onCanPlay = () => {
      // Only clear buffering state; don't auto-play
      usePlayerStore.setState((s) =>
        s.playerState === 'BUFFERING' ? { playerState: 'PAUSED' } : {},
      )
    }

    const onLoadedMetadata = () => {
      audioDurationRef.current = audio.duration * 1000
    }

    audio.addEventListener('timeupdate', onTimeUpdate)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('waiting', onWaiting)
    audio.addEventListener('canplay', onCanPlay)
    audio.addEventListener('loadedmetadata', onLoadedMetadata)

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('waiting', onWaiting)
      audio.removeEventListener('canplay', onCanPlay)
      audio.removeEventListener('loadedmetadata', onLoadedMetadata)
      audio.pause()
      audio.src = ''
      audioRef.current = null
    }
  }, [handleTimeUpdate, handleSegmentEnd])

  // ── Load new audio URL when segment changes ─────────────────────────────
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !lesson) return

    const segment = lesson.segments[currentSegmentIndex]
    if (!segment?.narration.audio_url) return

    const prevSrc = audio.src
    const newSrc = segment.narration.audio_url

    if (prevSrc !== newSrc) {
      audio.src = newSrc
      audio.load()
      audioDurationRef.current = 0
    }
  }, [currentSegmentIndex, lesson])

  // ── React to playerState changes ─────────────────────────────────────────
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    if (playerState === 'PLAYING') {
      // Guard: don't call play() if already playing
      if (audio.paused) {
        audio.play().catch((err) => {
          // Browser blocked autoplay — revert state to PAUSED
          console.warn('[Player] play() rejected:', err)
          usePlayerStore.setState({ playerState: 'PAUSED' })
        })
      }
    } else if (playerState === 'PAUSED' || playerState === 'IDLE') {
      if (!audio.paused) {
        audio.pause()
      }
    }
  }, [playerState])

  // ── Seek audio when store.currentTimeMs is set externally (e.g. rewind) ─
  // We use a subscription so we don't create a circular loop via handleTimeUpdate
  useEffect(() => {
    const unsub = usePlayerStore.subscribe(
      (s) => s.currentTimeMs,
      (ms) => {
        const audio = audioRef.current
        if (!audio) return
        // Only seek if the audio position is meaningfully different (>500ms drift)
        const audioMs = audio.currentTime * 1000
        if (Math.abs(audioMs - ms) > 500) {
          audio.currentTime = ms / 1000
        }
      },
    )
    return unsub
  }, [])

  // ── Public actions (wrap store actions with audio element access) ───────

  const play = useCallback(() => {
    store.play()
  }, [store])

  const pause = useCallback(() => {
    store.pause()
  }, [store])

  const seek = useCallback(
    (ms: number) => {
      const audio = audioRef.current
      if (audio) {
        audio.currentTime = ms / 1000
      }
      store.seek(ms)
    },
    [store],
  )

  const nextSegment = useCallback(() => {
    store.nextSegment()
  }, [store])

  const prevSegment = useCallback(() => {
    store.prevSegment()
  }, [store])

  return {
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
    audioDurationMs: audioDurationRef.current,
  }
}
