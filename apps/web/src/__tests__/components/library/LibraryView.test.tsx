import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryView } from '@/components/library/LibraryView';
import type { LessonStatusResponse } from '@/services/upload.service';
import type { LibraryData } from '@/services/library.service';

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

const DATA: LibraryData = {
  ready: [lesson({ lesson_id: 'les_ready' })],
  processing: [lesson({ lesson_id: 'les_processing', status: 'running', title: 'Processing Lesson' })],
  failed: [lesson({ lesson_id: 'les_failed', status: 'failed', title: 'Failed Lesson' })],
};

beforeEach(() => {
  pushMock.mockReset();
});

describe('LibraryView', () => {
  it('renders Ready/Processing/Failed tabs reflecting real generation status, not viewing progress', () => {
    render(<LibraryView initialData={DATA} />);

    expect(screen.getByRole('button', { name: /^Ready/ })).not.toBeNull();
    expect(screen.getByRole('button', { name: /^Processing/ })).not.toBeNull();
    expect(screen.getByRole('button', { name: /^Failed/ })).not.toBeNull();
    expect(screen.queryByText('In Progress')).toBeNull();
    expect(screen.queryByText('Completed')).toBeNull();
  });

  it('navigates to the lesson on a ready card click', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={DATA} />);

    await user.click(screen.getByText('SQL Injection Vectors'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/les_ready');
  });

  it('does not navigate on a processing or failed card click', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={DATA} />);

    await user.click(screen.getByText('Processing Lesson'));
    await user.click(screen.getByText('Failed Lesson'));

    expect(pushMock).not.toHaveBeenCalled();
  });

  it('renders no fabricated progress percentage or thumbnail image anywhere', () => {
    const { container } = render(<LibraryView initialData={DATA} />);

    expect(container.querySelector('img')).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it('shows the empty state when there are no lessons at all', () => {
    render(<LibraryView initialData={{ ready: [], processing: [], failed: [] }} />);

    expect(screen.getByText('No lessons found in this category.')).not.toBeNull();
  });
});
