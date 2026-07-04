import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryView } from '@/components/library/LibraryView';
import type { MockLesson } from '@/mocks/data/lessons';
import type { LibraryData } from '@/mocks/api/library';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

function makeLesson(overrides: Partial<MockLesson>): MockLesson {
  return {
    id: 'les_1',
    title: 'SQL Injection Vectors',
    chapterTitle: 'Chapter 3',
    durationSeconds: 1500,
    status: 'in_progress',
    progressPercent: 72,
    lastAccessed: new Date().toISOString(),
    thumbnailUrl: 'https://images.unsplash.com/photo-real-thumbnail-1',
    slides: [],
    timeline: [],
    ...overrides,
  };
}

const DATA: LibraryData = {
  inProgress: [makeLesson({ id: 'les_1' })],
  completed: [],
  processing: [],
  failed: [],
};

beforeEach(() => {
  pushMock.mockReset();
});

describe('LibraryView', () => {
  it('renders lesson.thumbnailUrl from the data layer instead of a locally-computed stock image', () => {
    const { container } = render(<LibraryView initialData={DATA} />);

    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toBe(DATA.inProgress[0].thumbnailUrl);
  });

  it('navigates to the lesson on card click', async () => {
    const user = userEvent.setup();
    render(<LibraryView initialData={DATA} />);

    await user.click(screen.getByText('SQL Injection Vectors'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/les_1');
  });
});
