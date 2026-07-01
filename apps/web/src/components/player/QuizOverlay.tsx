'use client';

import { useState } from 'react';
import type { QuizQuestion } from '@hie/shared/types/lesson';
import { usePlayerStore } from '@/stores/player.machine';

interface QuizOverlayProps {
  questions: QuizQuestion[];
}

export function QuizOverlay({ questions }: QuizOverlayProps) {
  const exitQuiz = usePlayerStore((s) => s.exitQuiz);

  const [questionIndex, setQuestionIndex] = useState(0);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const question = questions[questionIndex];
  if (!question) return null;

  const isCorrect = submitted && selectedIndex === question.correct_index;
  const isLast = questionIndex >= questions.length - 1;

  function handleSelect(idx: number) {
    if (!submitted) setSelectedIndex(idx);
  }

  function handleSubmit() {
    if (selectedIndex === null) return;
    setSubmitted(true);
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
    <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-[#0a0a0f]/90 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-[#13131c] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-white/5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[var(--accent-primary)] text-xs font-semibold uppercase tracking-wider">
              Quick Check
            </span>
            {questions.length > 1 && (
              <span className="text-neutral-500 text-xs">
                {questionIndex + 1} / {questions.length}
              </span>
            )}
          </div>
          <p className="text-white text-base font-medium leading-snug">
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

        {/* Explanation — shown after submit */}
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

        {/* Actions */}
        <div className="px-6 pb-6 flex justify-end gap-3">
          {!submitted ? (
            <button
              onClick={handleSubmit}
              disabled={selectedIndex === null}
              className="px-5 py-2 rounded-full bg-[var(--accent-primary)] hover:bg-[var(--accent-primary-hover)]
                         text-white text-sm font-medium transition-colors
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Submit
            </button>
          ) : (
            <button
              onClick={handleNext}
              className="px-5 py-2 rounded-full bg-[var(--accent-primary)] hover:bg-[var(--accent-primary-hover)]
                         text-white text-sm font-medium transition-colors"
            >
              {isLast ? 'Continue' : 'Next question'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
