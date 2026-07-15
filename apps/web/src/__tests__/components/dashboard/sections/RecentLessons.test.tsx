import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RecentLessons } from '@/components/dashboard/sections/RecentLessons';
import type { LessonStatusResponse } from '@/services/upload.service';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

function lesson(overrides: Partial<LessonStatusResponse> = {}): LessonStatusResponse {
  return {
    lesson_id: 'lsn_1',
    status: 'ready',
    title: 'SQL Injection Vectors',
    error: null,
    created_at: '2026-07-01T00:00:00Z',
    completed_at: '2026-07-01T00:05:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  pushMock.mockReset();
});

describe('RecentLessons', () => {
  it('renders nothing when there are no lessons and no error', () => {
    const { container } = render(<RecentLessons lessons={[]} error={null} />);

    expect(container.firstChild).toBeNull();
  });

  it('"View All" navigates to /library', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={[lesson()]} error={null} />);

    await user.click(screen.getByText('View All'));

    expect(pushMock).toHaveBeenCalledWith('/library');
  });

  it('a Ready lesson card is clickable and navigates to /lesson/{id}', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={[lesson({ lesson_id: 'lsn_9', status: 'ready' })]} error={null} />);

    await user.click(screen.getByText('SQL Injection Vectors'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/lsn_9');
  });

  it('a Generating lesson card is not clickable and shows a title fallback when title is null', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={[lesson({ status: 'running', title: null })]} error={null} />);

    expect(screen.getByText('Untitled Lesson')).not.toBeNull();
    await user.click(screen.getByText('Untitled Lesson'));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('shows status badges via formatLessonStatusLabel', () => {
    render(<RecentLessons lessons={[lesson({ status: 'failed' })]} error={null} />);

    expect(screen.getByText('Failed')).not.toBeNull();
  });

  it('shows an inline error instead of the card list when error is set, but still shows the heading and View All link', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={[]} error="We couldn't load your recent lessons right now." />);

    expect(screen.getByText("We couldn't load your recent lessons right now.")).not.toBeNull();
    expect(screen.getByText('Recently Added Lessons')).not.toBeNull();

    await user.click(screen.getByText('View All'));
    expect(pushMock).toHaveBeenCalledWith('/library');
  });

  it('an unrecognized status still shows a "Failed" badge and is not clickable, instead of a silent dead card', async () => {
    const user = userEvent.setup();
    // @ts-expect-error — intentionally out-of-union to simulate an unexpected backend value
    render(<RecentLessons lessons={[lesson({ status: 'cancelled' })]} error={null} />);

    expect(screen.getByText('Failed')).not.toBeNull();
    await user.click(screen.getByText('SQL Injection Vectors'));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('falls back to "Untitled Lesson" for an empty-string title, not just null', () => {
    render(<RecentLessons lessons={[lesson({ title: '' })]} error={null} />);

    expect(screen.getByText('Untitled Lesson')).not.toBeNull();
  });
});
