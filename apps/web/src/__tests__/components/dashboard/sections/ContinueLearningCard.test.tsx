import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContinueLearningCard } from '@/components/dashboard/sections/ContinueLearningCard';
import type { MockLesson } from '@/mocks/data/lessons';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

const LESSON: MockLesson = {
  id: 'les_1',
  title: 'SQL Injection Vectors',
  chapterTitle: 'Chapter 3: Database Security',
  durationSeconds: 1500,
  status: 'in_progress',
  progressPercent: 72,
  lastAccessed: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
  slides: [],
  timeline: [],
};

beforeEach(() => {
  pushMock.mockReset();
});

describe('ContinueLearningCard', () => {
  it('"View Path" navigates to /library', async () => {
    const user = userEvent.setup();
    render(<ContinueLearningCard lesson={LESSON} />);

    await user.click(screen.getByText('View Path'));

    expect(pushMock).toHaveBeenCalledWith('/library');
  });

  it('shows a real relative time derived from lesson.lastAccessed, not a hardcoded string', () => {
    render(<ContinueLearningCard lesson={LESSON} />);

    expect(screen.getByText(/Last opened 2 hours ago/)).not.toBeNull();
  });

  it('"Resume" navigates to the lesson without double-firing the card-level navigation', async () => {
    const user = userEvent.setup();
    render(<ContinueLearningCard lesson={LESSON} />);

    await user.click(screen.getByText('Resume'));

    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith('/lesson/les_1');
  });
});
