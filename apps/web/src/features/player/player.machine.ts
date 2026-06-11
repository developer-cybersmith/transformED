import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import type { LessonPackage, NarrationTimestamp } from '@transformed/shared/types/lesson'
import type { TutorState, InterventionType } from '@transformed/shared/types/ws'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PlayerState = 'IDLE' | 'PLAYING' | 'PAUSED' | 'BUFFERING'

export interface ActiveIntervention {
  type: InterventionType
  message: string
  action?: string
}

export interface PlayerStore {
  // ── Lesson data ──────────────────────────────────────────────────────────
  lesson: LessonPackage | null

  // ── Playback position ────────────────────────────────────────────────────
  currentSegmentIndex: number
  currentSlideIndex: number
  currentTimeMs: number

  // ── FSM states ───────────────────────────────────────────────────────────
  playerState: PlayerState
  tutorState: TutorState

  // ── Active intervention payload ──────────────────────────────────────────
  activeIntervention: ActiveIntervention | null

  // ── Quiz / teach-back state ──────────────────────────────────────────────
  isQuizOpen: boolean
  isTeachBackOpen: boolean

  // ── Actions ──────────────────────────────────────────────────────────────
  loadLesson: (lesson: LessonPackage) => void
  play: () => void
  pause: () => void
  seek: (ms: number) => void
  nextSegment: () => void
  prevSegment: () => void
  handleTimeUpdate: (ms: number) => void
  handleSegmentEnd: () => void
  handleTutorIntervention: (type: InterventionType, message: string, action?: string) => void
  acknowledgeIntervention: () => void
  openQuiz: () => void
  closeQuiz: () => void
  openTeachBack: () => void
  closeTeachBack: () => void
  setTutorState: (state: TutorState) => void
}

// ---------------------------------------------------------------------------
// Binary search — find which slide index is active at `timeMs`
// ---------------------------------------------------------------------------

function findSlideIndexAtTime(
  timestamps: NarrationTimestamp[],
  timeMs: number,
): number {
  if (!timestamps.length) return 0

  // Fast path: common case where we're within the first entry
  if (timeMs < timestamps[0].start_ms) return 0

  let lo = 0
  let hi = timestamps.length - 1
  let result = 0

  while (lo <= hi) {
    const mid = (lo + hi) >>> 1
    const entry = timestamps[mid]

    if (timeMs >= entry.start_ms && timeMs <= entry.end_ms) {
      // Direct hit — time is inside this slide's window
      return mid
    }

    if (timeMs > entry.end_ms) {
      // We're past this slide — it's still a candidate (last completed slide)
      result = mid
      lo = mid + 1
    } else {
      // timeMs < entry.start_ms — look left
      hi = mid - 1
    }
  }

  return result
}

// ---------------------------------------------------------------------------
// Zustand store
// ---------------------------------------------------------------------------

export const usePlayerStore = create<PlayerStore>()(
  subscribeWithSelector((set, get) => ({
    // ── Initial state ────────────────────────────────────────────────────
    lesson: null,
    currentSegmentIndex: 0,
    currentSlideIndex: 0,
    currentTimeMs: 0,
    playerState: 'IDLE',
    tutorState: 'IDLE',
    activeIntervention: null,
    isQuizOpen: false,
    isTeachBackOpen: false,

    // ── loadLesson ────────────────────────────────────────────────────────
    loadLesson: (lesson) => {
      set({
        lesson,
        currentSegmentIndex: 0,
        currentSlideIndex: 0,
        currentTimeMs: 0,
        playerState: 'IDLE',
        tutorState: 'TEACHING',
        activeIntervention: null,
        isQuizOpen: false,
        isTeachBackOpen: false,
      })
    },

    // ── Playback controls ─────────────────────────────────────────────────
    play: () => {
      const { playerState, tutorState } = get()
      // Only allow play if tutor isn't in an interrupting state
      if (tutorState === 'INTERVENING' || tutorState === 'QUIZZING' || tutorState === 'TEACH_BACK') return
      if (playerState !== 'PLAYING') {
        set({ playerState: 'PLAYING' })
      }
    },

    pause: () => {
      set((s) => s.playerState === 'PLAYING' ? { playerState: 'PAUSED' } : {})
    },

    seek: (ms: number) => {
      const { lesson, currentSegmentIndex } = get()
      if (!lesson) return

      const segment = lesson.segments[currentSegmentIndex]
      if (!segment) return

      const newSlideIndex = findSlideIndexAtTime(segment.narration.timestamps, ms)
      set({ currentTimeMs: ms, currentSlideIndex: newSlideIndex })
    },

    nextSegment: () => {
      const { lesson, currentSegmentIndex } = get()
      if (!lesson) return

      const nextIndex = currentSegmentIndex + 1
      if (nextIndex < lesson.segments.length) {
        set({
          currentSegmentIndex: nextIndex,
          currentSlideIndex: 0,
          currentTimeMs: 0,
          playerState: 'PAUSED',
          tutorState: 'TEACHING',
        })
      } else {
        // All segments complete — session end
        set({
          playerState: 'PAUSED',
          tutorState: 'SESSION_END',
        })
      }
    },

    prevSegment: () => {
      const { currentSegmentIndex } = get()
      if (currentSegmentIndex > 0) {
        set({
          currentSegmentIndex: currentSegmentIndex - 1,
          currentSlideIndex: 0,
          currentTimeMs: 0,
          playerState: 'PAUSED',
        })
      }
    },

    // ── handleTimeUpdate — called every ~250ms from the audio element ─────
    //
    // Core logic: given the new audio position in milliseconds, look up which
    // slide should be displayed using a binary search on narration.timestamps.
    // This is what keeps slides in sync with audio.
    //
    handleTimeUpdate: (ms: number) => {
      const { lesson, currentSegmentIndex, currentSlideIndex, playerState } = get()
      if (!lesson || playerState !== 'PLAYING') return

      const segment = lesson.segments[currentSegmentIndex]
      if (!segment) return

      const newSlideIndex = findSlideIndexAtTime(segment.narration.timestamps, ms)

      if (newSlideIndex !== currentSlideIndex) {
        set({ currentTimeMs: ms, currentSlideIndex: newSlideIndex })
      } else {
        set({ currentTimeMs: ms })
      }
    },

    // ── handleSegmentEnd — audio element `ended` event ────────────────────
    //
    // Transitions the tutor into CHECKING_IN mode (quiz + teach-back flow)
    // before advancing to the next segment.
    //
    handleSegmentEnd: () => {
      const { lesson, currentSegmentIndex } = get()
      if (!lesson) return

      const segment = lesson.segments[currentSegmentIndex]
      if (!segment) return

      set({ playerState: 'PAUSED', tutorState: 'CHECKING_IN' })

      // If the segment has quiz questions, open the quiz modal.
      if (segment.quiz.length > 0) {
        set({ tutorState: 'QUIZZING', isQuizOpen: true })
      } else if (segment.teachback_prompt) {
        // No quiz but has teach-back — go directly to teach-back
        set({ tutorState: 'TEACH_BACK', isTeachBackOpen: true })
      } else {
        // Nothing to check — just advance
        get().nextSegment()
      }
    },

    // ── handleTutorIntervention — called when WS delivers tutor_intervene ─
    handleTutorIntervention: (type, message, action) => {
      set({
        playerState: 'PAUSED',
        tutorState: 'INTERVENING',
        activeIntervention: { type, message, action },
      })
    },

    // ── acknowledgeIntervention ────────────────────────────────────────────
    acknowledgeIntervention: () => {
      const { activeIntervention } = get()
      if (!activeIntervention) return

      if (activeIntervention.type === 'confusion') {
        // Type B: replay last 60s — seek back, then play
        const { currentTimeMs } = get()
        const rewindMs = Math.max(0, currentTimeMs - 60_000)
        set({
          activeIntervention: null,
          tutorState: 'TEACHING',
          playerState: 'PAUSED',
          currentTimeMs: rewindMs,
        })
        // The usePlayer hook watches playerState and will seek the audio element
        // via the seekAudio callback registered in the hook.
        get().play()
      } else {
        set({
          activeIntervention: null,
          tutorState: 'TEACHING',
          playerState: 'PAUSED',
        })
        get().play()
      }
    },

    // ── Quiz controls ─────────────────────────────────────────────────────
    openQuiz: () => set({ isQuizOpen: true, tutorState: 'QUIZZING' }),
    closeQuiz: () => {
      // After quiz, move to teach-back if available
      const { lesson, currentSegmentIndex } = get()
      const segment = lesson?.segments[currentSegmentIndex]
      if (segment?.teachback_prompt) {
        set({ isQuizOpen: false, tutorState: 'TEACH_BACK', isTeachBackOpen: true })
      } else {
        set({ isQuizOpen: false })
        get().nextSegment()
      }
    },

    // ── Teach-back controls ───────────────────────────────────────────────
    openTeachBack: () => set({ isTeachBackOpen: true, tutorState: 'TEACH_BACK' }),
    closeTeachBack: () => {
      set({ isTeachBackOpen: false })
      get().nextSegment()
    },

    // ── setTutorState — used by WS state_change messages ─────────────────
    setTutorState: (state) => set({ tutorState: state }),
  })),
)
