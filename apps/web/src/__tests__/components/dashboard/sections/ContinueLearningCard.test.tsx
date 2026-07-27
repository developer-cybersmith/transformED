import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContinueLearningCard } from '@/components/dashboard/sections/ContinueLearningCard';
import type { LessonStatusResponse } from '@/services/upload.service';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

const LESSON: LessonStatusResponse = {
  lesson_id: 'les_1',
  status: 'ready',
  title: 'SQL Injection Vectors',
  error: null,
  created_at: '2026-07-24T10:00:00Z',
  completed_at: '2026-07-24T10:05:00Z',
  content: null,
};

beforeEach(() => {
  pushMock.mockReset();
});

describe('ContinueLearningCard', () => {
  it('renders nothing when there is no ready lesson', () => {
    const { container } = render(<ContinueLearningCard lesson={null} />);
    expect(container.textContent).toBe('');
  });

  it('"View Path" navigates to /library', async () => {
    const user = userEvent.setup();
    render(<ContinueLearningCard lesson={LESSON} />);

    await user.click(screen.getByText('View Path'));

    expect(pushMock).toHaveBeenCalledWith('/library');
  });

  it('shows a "Ready to continue" state instead of a fabricated progress percentage', () => {
    render(<ContinueLearningCard lesson={LESSON} />);

    expect(screen.getByText('Ready to continue')).not.toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it('"Resume" navigates to the lesson without double-firing the card-level navigation', async () => {
    const user = userEvent.setup();
    render(<ContinueLearningCard lesson={LESSON} />);

    await user.click(screen.getByText('Resume'));

    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith('/lesson/les_1');
  });

  it('falls back to "Untitled Lesson" when title is null', () => {
    render(<ContinueLearningCard lesson={{ ...LESSON, title: null }} />);

    expect(screen.getByText('Untitled Lesson')).not.toBeNull();
  });
});
