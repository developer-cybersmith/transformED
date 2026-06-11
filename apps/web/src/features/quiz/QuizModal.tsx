'use client'

import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { QuizQuestion } from '@transformed/shared/types/lesson'
import { CheckCircle, XCircle } from 'lucide-react'

interface QuizModalProps {
  questions: QuizQuestion[]
  onComplete: (score: number) => void
}

type AnswerRecord = { selected: number; correct: boolean }

export function QuizModal({ questions, onComplete }: QuizModalProps) {
  const [current, setCurrent] = useState(0)
  const [answers, setAnswers] = useState<Record<number, AnswerRecord>>({})
  const [selectedOption, setSelectedOption] = useState<number | null>(null)
  const [showExplanation, setShowExplanation] = useState(false)

  const question = questions[current]
  const isAnswered = showExplanation
  const isLast = current === questions.length - 1

  function handleOptionSelect(idx: number) {
    if (isAnswered) return
    setSelectedOption(idx)
  }

  function handleSubmitAnswer() {
    if (selectedOption === null) return
    const correct = selectedOption === question.correct_index
    setAnswers((prev) => ({ ...prev, [current]: { selected: selectedOption, correct } }))
    setShowExplanation(true)
  }

  function handleNext() {
    if (isLast) {
      const correct = Object.values({ ...answers }).filter((a) => a.correct).length
      const score = Math.round((correct / questions.length) * 100)
      onComplete(score)
    } else {
      setCurrent((c) => c + 1)
      setSelectedOption(null)
      setShowExplanation(false)
    }
  }

  const answered = answers[current]
  const progress = Math.round((Object.keys(answers).length / questions.length) * 100)

  return (
    <Dialog.Root open>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-700 bg-slate-800 p-8 shadow-2xl">
          {/* Header */}
          <div className="mb-5">
            <div className="mb-1.5 flex items-center justify-between text-xs text-slate-400">
              <span>Question {current + 1} of {questions.length}</span>
              <span className="capitalize text-slate-500">{question.difficulty}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
              <div
                className="h-full rounded-full bg-primary-600 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          <Dialog.Title className="mb-5 text-base font-semibold text-white">
            {question.question}
          </Dialog.Title>

          {/* Options */}
          <div className="mb-5 space-y-2.5">
            {question.options.map((option, idx) => {
              let variant = 'default'
              if (isAnswered) {
                if (idx === question.correct_index) variant = 'correct'
                else if (idx === answered?.selected && !answered.correct) variant = 'wrong'
              } else if (selectedOption === idx) {
                variant = 'selected'
              }

              const styles = {
                default:   'border-slate-600 bg-slate-700/50 text-slate-300 hover:border-slate-500 hover:bg-slate-700',
                selected:  'border-primary-500 bg-primary-900/30 text-white',
                correct:   'border-green-500 bg-green-900/30 text-green-300',
                wrong:     'border-red-500 bg-red-900/30 text-red-300',
              }[variant]

              return (
                <button
                  key={idx}
                  onClick={() => handleOptionSelect(idx)}
                  disabled={isAnswered}
                  className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-colors disabled:cursor-default ${styles}`}
                >
                  <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border border-current text-xs font-semibold">
                    {String.fromCharCode(65 + idx)}
                  </span>
                  <span>{option}</span>
                  {isAnswered && idx === question.correct_index && (
                    <CheckCircle className="ml-auto h-4 w-4 text-green-400" />
                  )}
                  {isAnswered && idx === answered?.selected && !answered.correct && (
                    <XCircle className="ml-auto h-4 w-4 text-red-400" />
                  )}
                </button>
              )
            })}
          </div>

          {/* Explanation */}
          {showExplanation && (
            <div className={`mb-5 rounded-xl border p-4 text-sm ${
              answered?.correct
                ? 'border-green-700 bg-green-900/20 text-green-300'
                : 'border-red-700 bg-red-900/20 text-red-300'
            }`}>
              <p className="mb-1 font-semibold">
                {answered?.correct ? '✓ Correct!' : '✗ Not quite.'}
              </p>
              <p className="text-slate-300">{question.explanation}</p>
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3">
            {!isAnswered ? (
              <button
                onClick={handleSubmitAnswer}
                disabled={selectedOption === null}
                className="rounded-xl bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
              >
                Check Answer
              </button>
            ) : (
              <button
                onClick={handleNext}
                className="rounded-xl bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
              >
                {isLast ? 'Finish Quiz' : 'Next Question →'}
              </button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
