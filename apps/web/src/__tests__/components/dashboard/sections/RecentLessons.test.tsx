import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RecentLessons } from '@/components/dashboard/sections/RecentLessons';
import type { MockLesson } from '@/mocks/data/lessons';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

const LESSONS: MockLesson[] = [
  {
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
  },
];

beforeEach(() => {
  pushMock.mockReset();
});

describe('RecentLessons', () => {
  it('"View All" navigates to /library', async () => {
    const user = userEvent.setup();
    render(<RecentLessons lessons={LESSONS} />);

    await user.click(screen.getByText('View All'));

    expect(pushMock).toHaveBeenCalledWith('/library');
  });

  it('renders lesson.thumbnailUrl from the data layer instead of a locally-computed stock image', () => {
    const { container } = render(<RecentLessons lessons={LESSONS} />);

    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toBe(LESSONS[0].thumbnailUrl);
  });

  it('hides the thumbnail image instead of showing a broken-image icon when it fails to load', () => {
    const { container } = render(<RecentLessons lessons={LESSONS} />);

    const img = container.querySelector('img')!;
    img.dispatchEvent(new Event('error'));

    expect(img.style.display).toBe('none');
  });
});
