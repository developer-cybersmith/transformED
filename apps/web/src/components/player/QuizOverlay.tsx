'use client';

import { useState, useRef, useEffect } from 'react';
import type { QuizQuestion } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';
import { submitQuiz, type QuizAnswer, type QuizResult } from '@/lib/assessment';

interface QuizOverlayProps {
  questions: QuizQuestion[];
}

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
export function QuizOverlay({ questions }: QuizOverlayProps) {
  const exitQuiz = usePlayerStore((s) => s.exitQuiz);
  const sessionId = usePlayerStore((s) => s.sessionId);
  const lesson = usePlayerStore((s) => s.lesson);
  const currentSegmentIndex = usePlayerStore((s) => s.currentSegmentIndex);

  const [questionIndex, setQuestionIndex] = useState(0);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<QuizResult | null>(null);

  // Collect answers across all questions; submitted at the end
  const collectedAnswers = useRef<QuizAnswer[]>([]);
  // Track when the current question became active for response_time_ms.
  // Date.now() is impure and must not be called during render — set it in an
  // effect keyed on questionIndex instead, covering both mount and advance.
  const questionStartMs = useRef<number | undefined>(undefined);
  useEffect(() => {
    questionStartMs.current = Date.now();
  }, [questionIndex]);

  const question = questions[questionIndex];
  if (!question) return null;

  const isCorrect = submitted && selectedIndex === question.correct_index;
  const isLast = questionIndex >= questions.length - 1;
  const segment = lesson?.segments[currentSegmentIndex];

  function handleSelect(idx: number) {
    if (!submitted) setSelectedIndex(idx);
  }

  async function handleSubmit() {
    if (selectedIndex === null) return;

    const answer: QuizAnswer = {
      question_id: question.question_id,
      response_index: selectedIndex,
      response_time_ms: Date.now() - questionStartMs.current!,
    };
    collectedAnswers.current = [...collectedAnswers.current, answer];
    setSubmitted(true);

    if (isLast && lesson && segment) {
      setIsSubmitting(true);
      try {
        const quizResult = await submitQuiz({
          session_id: sessionId,
          lesson_id: lesson.lesson_id,
          segment_id: segment.segment_id,
          answers: collectedAnswers.current,
        });
        setResult(quizResult);
      } catch {
        // API unavailable — don't block the student
      } finally {
        setIsSubmitting(false);
      }
    }
  }

  function handleNext() {
    if (isLast) {
      exitQuiz();
    } else {
      setQuestionIndex((i) => i + 1);
      setSelectedIndex(null);
      setSubmitted(false);
    }
  }

  function optionStyle(idx: number): string {
    const base =
      'w-full text-left px-4 py-3 rounded-xl border text-sm transition-colors duration-150 ';

    if (!submitted) {
      return base + (selectedIndex === idx
        ? 'border-[var(--accent-primary)] bg-[var(--accent-primary)]/10 text-white'
        : 'border-white/10 bg-white/5 text-neutral-300 hover:border-white/25 hover:text-white');
    }

    if (idx === question.correct_index) {
      return base + 'border-emerald-500 bg-emerald-500/10 text-emerald-300';
    }
    if (idx === selectedIndex) {
      return base + 'border-red-500 bg-red-500/10 text-red-300';
    }
    return base + 'border-white/5 bg-white/[0.02] text-neutral-500';
  }

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-primary-dark/90 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-[#07172C] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-white/5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[var(--accent-secondary)] text-xs font-semibold uppercase tracking-wider">
              Quick Check
            </span>
            {questions.length > 1 && (
              <span className="text-neutral-500 text-xs">
                {questionIndex + 1} / {questions.length}
              </span>
            )}
          </div>
          <p className="font-serif text-white text-lg font-medium leading-snug">
            {question.question}
          </p>
        </div>

        {/* Options */}
        <div className="px-6 py-4 space-y-2">
          {question.options.map((opt, idx) => (
            <button
              key={idx}
              onClick={() => handleSelect(idx)}
              disabled={submitted}
              className={optionStyle(idx)}
            >
              <span className="text-neutral-400 mr-2">
                {String.fromCharCode(65 + idx)}.
              </span>
              {opt}
            </button>
          ))}
        </div>

        {/* Per-question explanation */}
        {submitted && (
          <div className={[
            'mx-6 mb-4 px-4 py-3 rounded-xl text-sm',
            isCorrect
              ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
              : 'bg-red-500/10 text-red-300 border border-red-500/20',
          ].join(' ')}>
            <span className="font-semibold mr-1">{isCorrect ? 'Correct!' : 'Not quite.'}</span>
            {question.explanation}
          </div>
        )}

        {/* Score summary — shown after last question API returns */}
        {result && (
          <div className="mx-6 mb-4 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-sm space-y-1">
            <p className="text-white font-semibold">
              {result.correct_count}/{result.total_count} correct
              <span className="text-neutral-400 font-normal ml-2">
                ({Math.round(result.score)}%)
              </span>
            </p>
            {result.feedback.map((f) => (
              <p key={f.question_id} className={f.correct ? 'text-emerald-400' : 'text-red-400'}>
                {f.message}
              </p>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="px-6 pb-6 flex justify-end gap-3">
          {!submitted ? (
            <button
              onClick={handleSubmit}
              disabled={selectedIndex === null}
              className="px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                         text-primary text-sm font-semibold transition-all
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Submit
            </button>
          ) : (
            <button
              onClick={handleNext}
              disabled={isSubmitting}
              className="px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                         text-primary text-sm font-semibold transition-all
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isSubmitting ? 'Scoring…' : isLast ? 'Continue' : 'Next question'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
