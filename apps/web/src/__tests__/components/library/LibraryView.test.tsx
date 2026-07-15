import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryView } from '@/components/library/LibraryView';
import type { LibraryData } from '@/services/library.service';

const { pushMock, apiGetMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  apiGetMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/lib/api', () => ({
  api: { get: apiGetMock },
}));

function lesson(overrides: Partial<LibraryData['lessons'][number]> = {}) {
  return {
    lesson_id: 'lsn_1',
    status: 'ready' as const,
    title: 'SQL Injection Vectors',
    error: null,
    created_at: '2026-07-01T00:00:00Z',
    completed_at: '2026-07-01T00:05:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  pushMock.mockReset();
  apiGetMock.mockReset();
});

describe('LibraryView', () => {
  it('shows the empty state with an Upload CTA when there are no lessons at all', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={{ lessons: [] }} />);

    expect(screen.getByText(/No lessons yet/i)).not.toBeNull();
    await user.click(screen.getByText('Upload a PDF'));
    expect(pushMock).toHaveBeenCalledWith('/upload');
  });

  it('renders tabs with correct counts across mixed statuses', () => {
    const lessons = [
      lesson({ lesson_id: 'l1', status: 'ready' }),
      lesson({ lesson_id: 'l2', status: 'running', title: null }),
      lesson({ lesson_id: 'l3', status: 'queued', title: null }),
      lesson({ lesson_id: 'l4', status: 'failed', error: 'Cost ceiling exceeded' }),
    ];
    render(<LibraryView initialData={{ lessons }} />);

    expect(screen.getByRole('button', { name: /^All Lessons/ }).querySelector('span')?.textContent).toBe('4');
    expect(screen.getByRole('button', { name: /^Generating/ }).querySelector('span')?.textContent).toBe('2');
    expect(screen.getByRole('button', { name: /^Ready/ }).querySelector('span')?.textContent).toBe('1');
    expect(screen.getByRole('button', { name: /^Failed/ }).querySelector('span')?.textContent).toBe('1');
  });

  it('a Ready card is clickable and navigates to /lesson/{id}', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={{ lessons: [lesson({ lesson_id: 'lsn_42', status: 'ready' })] }} />);

    await user.click(screen.getByText('SQL Injection Vectors'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/lsn_42');
  });

  it('a Generating card is not clickable and shows a title fallback when title is null', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={{ lessons: [lesson({ status: 'running', title: null })] }} />);

    expect(screen.getByText('Untitled Lesson')).not.toBeNull();
    await user.click(screen.getByText('Untitled Lesson'));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('a Failed card shows its error message and an "Upload Again" button that routes to /upload without navigating to the lesson', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={{ lessons: [lesson({ status: 'failed', error: 'Cost ceiling exceeded' })] }} />);

    expect(screen.getByText('Cost ceiling exceeded')).not.toBeNull();
    await user.click(screen.getByText('Upload Again'));

    expect(pushMock).toHaveBeenCalledWith('/upload');
    expect(pushMock).not.toHaveBeenCalledWith('/lesson/lsn_1');
  });

  it('a Failed card falls back to a generic message when error is null', () => {
    render(<LibraryView initialData={{ lessons: [lesson({ status: 'failed', error: null })] }} />);

    expect(screen.getByText('Generation failed — please try again.')).not.toBeNull();
  });

  it('shows "No lessons found in this category" when a tab has zero matches but the library is not empty', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={{ lessons: [lesson({ status: 'ready' })] }} />);

    await user.click(screen.getByText('Failed'));

    expect(screen.getByText('No lessons found in this category.')).not.toBeNull();
  });

  it('shows a "Load more" button when the initial page is full, fetches the next page, and appends results', async () => {
    const user = userEvent.setup();
    const fullPage = Array.from({ length: 24 }, (_, i) => lesson({ lesson_id: `l${i}`, title: `Lesson ${i}` }));
    apiGetMock.mockResolvedValue({ data: [lesson({ lesson_id: 'l24', title: 'Lesson 24' })] });

    render(<LibraryView initialData={{ lessons: fullPage }} />);

    const loadMoreButton = screen.getByText('Load more');
    await user.click(loadMoreButton);

    expect(apiGetMock).toHaveBeenCalledWith('content/lessons', { params: { limit: 24, offset: 24 } });
    await waitFor(() => expect(screen.getByText('Lesson 24')).not.toBeNull());
  });

  it('does not show "Load more" when the initial page is short', () => {
    const shortPage = [lesson({ lesson_id: 'l1' })];
    render(<LibraryView initialData={{ lessons: shortPage }} />);

    expect(screen.queryByText('Load more')).toBeNull();
  });

  it('"Load more" hides itself once the fetched page is short', async () => {
    const user = userEvent.setup();
    const fullPage = Array.from({ length: 24 }, (_, i) => lesson({ lesson_id: `l${i}` }));
    apiGetMock.mockResolvedValue({ data: [lesson({ lesson_id: 'last' })] });

    render(<LibraryView initialData={{ lessons: fullPage }} />);
    await user.click(screen.getByText('Load more'));

    await waitFor(() => expect(screen.queryByText('Load more')).toBeNull());
  });
});
