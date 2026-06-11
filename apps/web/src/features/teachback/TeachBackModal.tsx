'use client'

import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/api/client'

interface TeachBackResponse {
  score: number          // 0–100
  praise: string
  correction: string | null
}

interface TeachBackModalProps {
  segmentId: string
  prompt: string
  onComplete: () => void
}

type Phase = 'input' | 'submitting' | 'result' | 'retry'

export function TeachBackModal({ segmentId, prompt, onComplete }: TeachBackModalProps) {
  const [phase, setPhase] = useState<Phase>('input')
  const [text, setText] = useState('')
  const [result, setResult] = useState<TeachBackResponse | null>(null)
  const [retryText, setRetryText] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submitResponse(responseText: string) {
    setError(null)
    setPhase('submitting')
    try {
      const res = await apiClient.post<TeachBackResponse>('/api/assessment/teachback', {
        segment_id: segmentId,
        response: responseText,
      })
      setResult(res)
      setPhase('result')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submission failed. Please try again.')
      setPhase(phase === 'input' ? 'input' : 'retry')
    }
  }

  function handleFirstSubmit() {
    if (text.trim().length < 10) return
    submitResponse(text.trim())
  }

  function handleRetrySubmit() {
    if (retryText.trim().length < 10) return
    submitResponse(retryText.trim())
  }

  const isLowScore = result !== null && result.score < 60
  const isRetryPhase = phase === 'retry'

  return (
    <Dialog.Root open>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-700 bg-slate-800 p-8 shadow-2xl">

          <Dialog.Title className="mb-2 text-lg font-semibold text-white">
            Teach it back
          </Dialog.Title>
          <Dialog.Description className="mb-5 text-sm text-slate-400">
            {prompt}
          </Dialog.Description>

          {/* Submission error */}
          {error && (
            <div className="mb-4 rounded-lg bg-red-900/30 border border-red-700 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          {/* Phase: input */}
          {phase === 'input' && (
            <>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={6}
                placeholder="Explain the concept in your own words…"
                className="mb-4 w-full resize-none rounded-xl border border-slate-600 bg-slate-700 px-4 py-3 text-sm text-white placeholder-slate-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
              />
              <div className="flex justify-end gap-3">
                {/* Always allow continuing — never gates progress */}
                <button
                  onClick={onComplete}
                  className="rounded-xl border border-slate-600 px-5 py-2.5 text-sm font-medium text-slate-400 hover:bg-slate-700 transition-colors"
                >
                  Skip for now
                </button>
                <button
                  onClick={handleFirstSubmit}
                  disabled={text.trim().length < 10}
                  className="rounded-xl bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                >
                  Submit
                </button>
              </div>
            </>
          )}

          {/* Phase: submitting */}
          {phase === 'submitting' && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary-500" />
              <span className="ml-3 text-sm text-slate-400">Evaluating your response…</span>
            </div>
          )}

          {/* Phase: result */}
          {(phase === 'result' || phase === 'retry') && result && (
            <div className="mb-5 space-y-4">
              {/* Score */}
              <div className="flex items-center gap-4 rounded-xl border border-slate-600 bg-slate-700/50 p-4">
                <div
                  className={`flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-full text-xl font-bold ${
                    result.score >= 80
                      ? 'bg-green-900/50 text-green-400'
                      : result.score >= 60
                      ? 'bg-yellow-900/50 text-yellow-400'
                      : 'bg-red-900/50 text-red-400'
                  }`}
                >
                  {result.score}
                </div>
                <div>
                  <p className="font-semibold text-white">{result.praise}</p>
                  {result.correction && (
                    <p className="mt-1 text-sm text-slate-300">{result.correction}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* One retry if score < 60 (feedback stays visible) */}
          {phase === 'result' && isLowScore && (
            <>
              <p className="mb-3 text-sm font-medium text-slate-300">
                Want to try once more with the feedback above?
              </p>
              <textarea
                value={retryText}
                onChange={(e) => setRetryText(e.target.value)}
                rows={5}
                placeholder="Try again in your own words…"
                className="mb-4 w-full resize-none rounded-xl border border-slate-600 bg-slate-700 px-4 py-3 text-sm text-white placeholder-slate-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
              />
              <div className="flex justify-end gap-3">
                <button
                  onClick={onComplete}
                  className="rounded-xl border border-slate-600 px-5 py-2.5 text-sm font-medium text-slate-400 hover:bg-slate-700 transition-colors"
                >
                  Continue anyway
                </button>
                <button
                  onClick={handleRetrySubmit}
                  disabled={retryText.trim().length < 10 || phase === 'submitting'}
                  className="rounded-xl bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                >
                  Resubmit
                </button>
              </div>
            </>
          )}

          {/* Score >= 60 or after retry — show Continue */}
          {phase === 'result' && !isLowScore && (
            <div className="flex justify-end">
              <button
                onClick={onComplete}
                className="rounded-xl bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
              >
                Continue →
              </button>
            </div>
          )}

          {/* After retry — always allow continuing */}
          {phase === 'retry' && result && (
            <div className="flex justify-end">
              <button
                onClick={onComplete}
                className="rounded-xl bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
              >
                Continue →
              </button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
