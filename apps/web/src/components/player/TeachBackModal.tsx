'use client';

import { useState } from 'react';
import { usePlayerStore } from '@/stores/player.machine';

interface TeachBackModalProps {
  prompt: string;
  segmentTitle: string;
}

export function TeachBackModal({ prompt, segmentTitle }: TeachBackModalProps) {
  const exitTeachBack = usePlayerStore((s) => s.exitTeachBack);
  const [text, setText] = useState('');

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center p-6 bg-[#0a0a0f]/90 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-[#13131c] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-white/5">
          <span className="text-[var(--accent-primary)] text-xs font-semibold uppercase tracking-wider block mb-1">
            Teach It Back
          </span>
          <p className="text-neutral-400 text-xs mb-3">
            {segmentTitle}
          </p>
          <p className="text-white text-sm leading-relaxed">
            {prompt}
          </p>
        </div>

        {/* Text area */}
        <div className="px-6 py-4">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Type your explanation here…"
            rows={5}
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3
                       text-white text-sm placeholder:text-neutral-600
                       focus:outline-none focus:border-[var(--accent-primary)]/50
                       resize-none transition-colors"
          />
        </div>

        {/* Actions */}
        <div className="px-6 pb-6 flex justify-between items-center">
          <button
            onClick={exitTeachBack}
            className="text-neutral-500 hover:text-neutral-300 text-sm transition-colors"
          >
            Skip
          </button>
          <button
            onClick={exitTeachBack}
            className="px-5 py-2 rounded-full bg-[var(--accent-primary)] hover:bg-[var(--accent-primary-hover)]
                       text-white text-sm font-medium transition-colors"
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
