import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RecentLessons } from '@/components/dashboard/sections/RecentLessons';
import type { LessonStatusResponse } from '@/services/upload.service';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

function lesson(overrides: Partial<LessonStatusResponse>): LessonStatusResponse {
  return {
    lesson_id: 'les_1',
    status: 'ready',
    title: 'SQL Injection Vectors',
    error: null,
    created_at: '2026-07-24T10:00:00Z',
    completed_at: '2026-07-24T10:05:00Z',
    content: null,
    ...overrides,
  };
}

const LESSONS: LessonStatusResponse[] = [lesson({})];

beforeEach(() => {
  pushMock.mockReset();
});

describe('RecentLessons', () => {
  it('renders nothing when there are no lessons', () => {
    const { container } = render(<RecentLessons lessons={[]} />);
    expect(container.textContent).toBe('');
  });

  it('"View All" navigates to /library', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={LESSONS} />);

    await user.click(screen.getByText('View All'));

    expect(pushMock).toHaveBeenCalledWith('/library');
  });

  it('clicking a lesson card navigates to /lesson/{lesson_id}', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={LESSONS} />);

    await user.click(screen.getByText('SQL Injection Vectors'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/les_1');
  });

  it('shows a real status label derived from lesson.status, not a fabricated progress percentage', () => {
    render(<RecentLessons lessons={[lesson({ status: 'ready' }), lesson({ lesson_id: 'les_2', status: 'running' }), lesson({ lesson_id: 'les_3', status: 'failed' })]} />);

    expect(screen.getByText('Ready')).not.toBeNull();
    expect(screen.getByText('Processing')).not.toBeNull();
    expect(screen.getByText('Failed')).not.toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it('falls back to "Untitled Lesson" when title is null', () => {
    render(<RecentLessons lessons={[lesson({ title: null })]} />);

    expect(screen.getByText('Untitled Lesson')).not.toBeNull();
  });

  it('does NOT navigate when clicking a processing or failed card — the lesson has no content to view yet', async () => {
    const user = userEvent.setup();
    render(
      <RecentLessons
        lessons={[
          lesson({ lesson_id: 'les_processing', status: 'running', title: 'Processing Lesson' }),
          lesson({ lesson_id: 'les_failed', status: 'failed', title: 'Failed Lesson' }),
        ]}
      />
    );

    await user.click(screen.getByText('Processing Lesson'));
    await user.click(screen.getByText('Failed Lesson'));

    expect(pushMock).not.toHaveBeenCalled();
  });
});
