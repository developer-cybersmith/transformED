'use client'

import { useState } from 'react'
import { Eye, HelpCircle, Coffee } from 'lucide-react'
import type { InterventionType } from '@transformed/shared/types/ws'

interface TutorInterventionCardProps {
  type: InterventionType
  message: string
  onAcknowledge: () => void
}

const ICON_MAP = {
  distraction: Eye,
  confusion: HelpCircle,
  fatigue: Coffee,
}

const COLOR_MAP = {
  distraction: {
    bg: 'bg-amber-900/40',
    border: 'border-amber-600',
    icon: 'text-amber-400',
    iconBg: 'bg-amber-900/50',
  },
  confusion: {
    bg: 'bg-blue-900/40',
    border: 'border-blue-600',
    icon: 'text-blue-400',
    iconBg: 'bg-blue-900/50',
  },
  fatigue: {
    bg: 'bg-purple-900/40',
    border: 'border-purple-600',
    icon: 'text-purple-400',
    iconBg: 'bg-purple-900/50',
  },
}

export function TutorInterventionCard({ type, message, onAcknowledge }: TutorInterventionCardProps) {
  const [breakTimer, setBreakTimer] = useState<number | null>(null)

  const Icon = ICON_MAP[type]
  const colors = COLOR_MAP[type]

  // Type C — fatigue — "Take a Break" starts a 5-minute countdown
  function handleTakeBreak() {
    setBreakTimer(5 * 60)
    const interval = setInterval(() => {
      setBreakTimer((t) => {
        if (t === null || t <= 1) {
          clearInterval(interval)
          onAcknowledge()
          return null
        }
        return t - 1
      })
    }, 1000)
  }

  function formatCountdown(secs: number) {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div
      className={`w-full max-w-sm rounded-2xl border p-6 shadow-2xl ${colors.bg} ${colors.border}`}
    >
      {/* Icon */}
      <div className={`mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl ${colors.iconBg}`}>
        <Icon className={`h-6 w-6 ${colors.icon}`} />
      </div>

      {/* Message */}
      <p className="mb-6 text-base font-medium text-white">{message}</p>

      {/* Type A — distraction */}
      {type === 'distraction' && (
        <button
          onClick={onAcknowledge}
          className="w-full rounded-xl bg-amber-600 py-2.5 text-sm font-semibold text-white hover:bg-amber-700 transition-colors"
        >
          Continue
        </button>
      )}

      {/* Type B — confusion — auto-replay handled in store; just acknowledge */}
      {type === 'confusion' && (
        <button
          onClick={onAcknowledge}
          className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
        >
          Replay last 60 seconds
        </button>
      )}

      {/* Type C — fatigue */}
      {type === 'fatigue' && (
        <div className="space-y-3">
          {breakTimer !== null ? (
            <div className="text-center">
              <p className="mb-2 text-sm text-slate-300">Break ends in</p>
              <p className="text-4xl font-bold tabular-nums text-purple-300">
                {formatCountdown(breakTimer)}
              </p>
            </div>
          ) : (
            <>
              <button
                onClick={handleTakeBreak}
                className="w-full rounded-xl bg-purple-600 py-2.5 text-sm font-semibold text-white hover:bg-purple-700 transition-colors"
              >
                Take a 5-Minute Break
              </button>
              <button
                onClick={onAcknowledge}
                className="w-full rounded-xl border border-slate-600 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-700 transition-colors"
              >
                Keep Going
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
