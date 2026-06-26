import React from 'react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import type { MockLesson } from '@/mocks/data/lessons';

// framer-motion uses ResizeObserver internally
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// next/link requires a router context — stub it
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    React.createElement('a', { href, ...props }, children),
}));

import { InteractivePlayer } from '@/components/lesson/InteractivePlayer';

const tbLesson: MockLesson = {
  id: 'les_test',
  title: 'Teach-Back Test Lesson',
  chapterTitle: 'Chapter 1',
  durationSeconds: 60,
  status: 'in_progress',
  progressPercent: 0,
  lastAccessed: '2026-06-26',
  slides: [],
  timeline: [
    { id: 'tb_1', type: 'teachback', timestamp: 0, prompt: 'Explain photosynthesis in your own words.' },
  ],
};

describe('InteractivePlayer — teach-back section', () => {
  it('renders textarea for typed response — no Mic or voice copy', async () => {
    await act(async () => {
      render(<InteractivePlayer initialLesson={tbLesson} />);
    });

    const textarea = document.querySelector('textarea');
    expect(textarea).not.toBeNull();
    expect(textarea?.getAttribute('placeholder')).toContain('Type your explanation');

    // No voice/STT copy present
    expect(screen.queryByText(/speak your answer aloud/i)).toBeNull();
  });

  it('"Submit & Continue" button is disabled when textarea is empty', async () => {
    await act(async () => {
      render(<InteractivePlayer initialLesson={tbLesson} />);
    });

    const submitBtn = screen.queryByRole('button', { name: /submit.*continue/i });
    expect(submitBtn).not.toBeNull();
    expect(submitBtn?.hasAttribute('disabled')).toBe(true);
  });

  it('prompt text from lesson is shown in teach-back card', async () => {
    await act(async () => {
      render(<InteractivePlayer initialLesson={tbLesson} />);
    });

    expect(screen.getByText(/Explain photosynthesis/i)).toBeTruthy();
  });
});
