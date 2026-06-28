'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { api } from '@/lib/api'

// ---------------------------------------------------------------------------
// Assessment questions — 3 dimensions: Cognitive (8), Emotional (5), Self-Direction (7)
// ---------------------------------------------------------------------------

type Dimension = 'cognitive' | 'emotional' | 'self_direction'

interface Question {
  id: string
  dimension: Dimension
  text: string
  options: string[]
}

const QUESTIONS: Question[] = [
  // Cognitive — 8
  { id: 'c1', dimension: 'cognitive', text: 'When learning something new, I prefer to:', options: ['See the big picture first, then details', 'Start with specific examples, then generalise', 'Work through step-by-step instructions', 'Discover patterns on my own'] },
  { id: 'c2', dimension: 'cognitive', text: 'I understand abstract concepts best when they are:', options: ['Explained with diagrams or visuals', 'Explained with real-world analogies', 'Broken into numbered steps', 'Linked to prior knowledge I already have'] },
  { id: 'c3', dimension: 'cognitive', text: 'When I encounter a difficult problem, I typically:', options: ['Break it into smaller sub-problems', 'Look for a similar problem I\'ve solved before', 'Think about it holistically before diving in', 'Try different approaches until one works'] },
  { id: 'c4', dimension: 'cognitive', text: 'My attention span during focused study is roughly:', options: ['Less than 15 minutes', '15–30 minutes', '30–45 minutes', 'More than 45 minutes'] },
  { id: 'c5', dimension: 'cognitive', text: 'How do you best retain new information?', options: ['Repetition and practice', 'Teaching it to someone else', 'Making notes in my own words', 'Connecting it to a story or narrative'] },
  { id: 'c6', dimension: 'cognitive', text: 'When reading technical text, I prefer:', options: ['Dense, detailed explanations', 'Concise summaries with key points', 'Examples and code/math alongside theory', 'Narrative writing with minimal jargon'] },
  { id: 'c7', dimension: 'cognitive', text: 'How comfortable are you with ambiguity while learning?', options: ['Very comfortable — I enjoy open-ended exploration', 'Somewhat comfortable', 'I prefer clear answers but can tolerate some uncertainty', 'I strongly prefer clear, definite answers'] },
  { id: 'c8', dimension: 'cognitive', text: 'Which type of quiz question do you find most useful for learning?', options: ['Multiple-choice recall', 'Short written explanation', 'Problem-solving / worked example', 'Real-world application scenario'] },

  // Emotional — 5
  { id: 'e1', dimension: 'emotional', text: 'When I get a wrong answer on a quiz, I feel:', options: ['Motivated to understand why', 'Briefly discouraged, then I move on', 'Quite frustrated', 'Indifferent — I focus on the next question'] },
  { id: 'e2', dimension: 'emotional', text: 'Praise and encouragement during study:', options: ['Significantly boosts my motivation', 'Helps somewhat', 'Makes little difference to me', 'Can feel patronising — I prefer neutral feedback'] },
  { id: 'e3', dimension: 'emotional', text: 'How does time pressure (e.g. timed quizzes) affect you?', options: ['I perform better under pressure', 'It slightly stresses me but I manage', 'It significantly impairs my thinking', 'I strongly dislike it and avoid it'] },
  { id: 'e4', dimension: 'emotional', text: 'When I\'m confused by a concept, my first reaction is:', options: ['Curiosity — I want to dig deeper', 'Mild anxiety, but I push through', 'I feel stuck and need a hint', 'I feel anxious and want to move on'] },
  { id: 'e5', dimension: 'emotional', text: 'How do you feel about having an AI track your engagement during learning?', options: ['Excited — I want personalised help', 'Fine, as long as my privacy is protected', 'Slightly uncomfortable but willing to try', 'I would prefer to opt out'] },

  // Self-Direction — 7
  { id: 's1', dimension: 'self_direction', text: 'How often do you set explicit learning goals before studying?', options: ['Always — I make detailed plans', 'Usually', 'Occasionally', 'Rarely or never'] },
  { id: 's2', dimension: 'self_direction', text: 'When given free choice on a topic to study, you:', options: ['Dive in immediately with a structured plan', 'Explore broadly before focusing', 'Wait for specific guidance', 'Feel overwhelmed and delay starting'] },
  { id: 's3', dimension: 'self_direction', text: 'How do you prefer to pace your lessons?', options: ['I want full control over pacing', 'Guided pacing with ability to override', 'Mostly guided, with occasional choices', 'Fully guided — tell me what comes next'] },
  { id: 's4', dimension: 'self_direction', text: 'How do you typically respond to a learning setback?', options: ['I analyse what went wrong and adjust', 'I take a short break then retry', 'I ask for help or hints', 'I often give up on that topic for now'] },
  { id: 's5', dimension: 'self_direction', text: 'I review my own understanding of a topic:', options: ['Regularly, through self-testing', 'Occasionally, when I feel uncertain', 'Rarely — I rely on external tests', 'Almost never'] },
  { id: 's6', dimension: 'self_direction', text: 'Which best describes your study consistency?', options: ['I study every day at fixed times', 'I study most days, flexible schedule', 'I study in bursts when motivated', 'I study primarily close to deadlines'] },
  { id: 's7', dimension: 'self_direction', text: 'When you finish a lesson, you typically:', options: ['Immediately review and summarise notes', 'Reflect briefly, then move on', 'Check off a to-do and move on', 'Rarely do anything after finishing'] },
]

const TOTAL = QUESTIONS.length

export default function OnboardingPage() {
  const router = useRouter()
  const [current, setCurrent] = useState(0)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const question = QUESTIONS[current]
  const progress = Math.round(((current) / TOTAL) * 100)
  const selectedAnswer = answers[question.id]

  function handleSelect(index: number) {
    setAnswers((prev) => ({ ...prev, [question.id]: index }))
  }

  function handleNext() {
    if (current < TOTAL - 1) {
      setCurrent((c) => c + 1)
    }
  }

  function handleBack() {
    if (current > 0) setCurrent((c) => c - 1)
  }

  async function handleSubmit() {
    setSubmitting(true)
    setError(null)
    try {
      const responses = QUESTIONS.map((q) => ({
        question_id: q.id,
        dimension: q.dimension,
        selected_index: answers[q.id] ?? 0,
        selected_text: q.options[answers[q.id] ?? 0],
      }))
      await api.post('assessment/onboarding/submit', { responses })
      router.push('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submission failed. Please try again.')
      setSubmitting(false)
    }
  }

  const isLast = current === TOTAL - 1
  const canProceed = selectedAnswer !== undefined

  const dimensionLabel: Record<Dimension, string> = {
    cognitive: 'Cognitive Style',
    emotional: 'Emotional Profile',
    self_direction: 'Self-Direction',
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4 py-12 dark:bg-slate-900">
      <div className="w-full max-w-xl">
        <div className="mb-8 text-center">
          <span className="text-xl font-bold text-primary-600">TransformED AI</span>
          <h1 className="mt-3 text-2xl font-semibold text-slate-900 dark:text-white">
            Learner DNA Assessment
          </h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            20 quick questions to personalise every lesson for you.
          </p>
        </div>

        {/* Progress bar */}
        <div className="mb-6">
          <div className="mb-1.5 flex items-center justify-between text-xs text-slate-400">
            <span>Question {current + 1} of {TOTAL}</span>
            <span className="font-medium text-primary-600">
              {dimensionLabel[question.dimension]}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className="h-full rounded-full bg-primary-600 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Question card */}
        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <p className="mb-6 text-base font-medium text-slate-900 dark:text-white">
            {question.text}
          </p>

          <div className="space-y-3">
            {question.options.map((option, idx) => (
              <button
                key={idx}
                onClick={() => handleSelect(idx)}
                className={`w-full rounded-lg border px-4 py-3 text-left text-sm transition-colors ${
                  selectedAnswer === idx
                    ? 'border-primary-500 bg-primary-50 text-primary-700 dark:border-primary-500 dark:bg-primary-900/20 dark:text-primary-300'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-primary-300 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-300 dark:hover:border-primary-600 dark:hover:bg-slate-600'
                }`}
              >
                <span className="mr-3 font-semibold text-slate-400 dark:text-slate-500">
                  {String.fromCharCode(65 + idx)}.
                </span>
                {option}
              </button>
            ))}
          </div>

          {error && (
            <div className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </div>
          )}

          <div className="mt-8 flex items-center justify-between">
            <button
              onClick={handleBack}
              disabled={current === 0}
              className="text-sm font-medium text-slate-500 hover:text-slate-700 disabled:opacity-30 dark:text-slate-400 dark:hover:text-slate-200"
            >
              Back
            </button>

            {isLast ? (
              <button
                onClick={handleSubmit}
                disabled={!canProceed || submitting}
                className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
              >
                {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                {submitting ? 'Saving…' : 'Complete Assessment'}
              </button>
            ) : (
              <button
                onClick={handleNext}
                disabled={!canProceed}
                className="rounded-lg bg-primary-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
              >
                Next
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
