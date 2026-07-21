import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

const { getMountCount, resetMountCount, incrementMountCount } = vi.hoisted(() => {
  let mountCount = 0;
  return {
    getMountCount: () => mountCount,
    resetMountCount: () => { mountCount = 0; },
    incrementMountCount: () => { mountCount += 1; },
  };
});

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('@/hooks/useLesson', () => ({
  useLesson: vi.fn(),
}));

// next/dynamic returns the loading component on first render in test env.
// We resolve it to the actual component after controlling the hook state.
vi.mock('next/dynamic', () => ({
  default: (importFn: () => Promise<{ default: React.ComponentType<unknown> }>, opts?: { loading?: () => React.ReactNode }) => {
    // In jsdom, return a stub that renders the loading fallback or a placeholder.
    // The mount-effect increments a module-level counter (not React state) so a
    // real unmount+remount (vs. an in-place prop update) is observable across renders.
    const MockPlayer = ({ lesson }: { lesson: typeof mockLessonPackage }) => {
      useEffect(() => {
        incrementMountCount();
      }, []);
      return <div data-testid="player-stub">{lesson.metadata.title}</div>;
    };
    return MockPlayer;
  },
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { PlayerLoader } from '@/components/player/PlayerLoader';
import { useLesson } from '@/hooks/useLesson';
import type React from 'react';

const mockUseLesson = vi.mocked(useLesson);

// ── Tests ────────────────────────────────────────────────────────────────────

describe('PlayerLoader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetMountCount();
  });

  it('renders PlayerSkeleton while lesson is loading', () => {
    mockUseLesson.mockReturnValue({ lesson: null, isLoading: true, error: null });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('player-skeleton')).toBeDefined();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
    expect(screen.queryByTestId('player-stub')).toBeNull();
  });

  it('renders LessonErrorState when the fetch completes with a null lesson (no explicit error)', () => {
    // A completed fetch (isLoading: false) with no lesson and no error is treated as
    // an error state, not a skeleton — see PlayerLoader.tsx's own comment on this branch.
    mockUseLesson.mockReturnValue({ lesson: null, isLoading: false, error: null });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-error')).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
  });

  it('renders LessonErrorState when hook returns an error', () => {
    mockUseLesson.mockReturnValue({
      lesson: null,
      isLoading: false,
      error: new Error('Lesson not found'),
    });

    render(<PlayerLoader lessonId="lesson_404" />);

    expect(screen.getByTestId('lesson-error')).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
  });

  it('renders Player when lesson is loaded successfully', () => {
    mockUseLesson.mockReturnValue({
      lesson: mockLessonPackage,
      isLoading: false,
      error: null,
    });

    render(<PlayerLoader lessonId="lesson_mock_1" />);

    expect(screen.getByTestId('player-stub')).toBeDefined();
    expect(screen.getByText(mockLessonPackage.metadata.title)).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
  });

  it('passes the lessonId to useLesson', () => {
    mockUseLesson.mockReturnValue({ lesson: null, isLoading: true, error: null });

    render(<PlayerLoader lessonId="lesson_xyz" />);

    expect(mockUseLesson).toHaveBeenCalledWith('lesson_xyz');
  });

  it('remounts Player (not just re-renders) when the loaded lesson changes to a different lesson_id (S2-06 review fix)', () => {
    const lessonA = { ...mockLessonPackage, lesson_id: 'lesson_A' };
    const lessonB = { ...mockLessonPackage, lesson_id: 'lesson_B' };

    mockUseLesson.mockReturnValue({ lesson: lessonA, isLoading: false, error: null });
    const { rerender } = render(<PlayerLoader lessonId="lesson_A" />);
    expect(getMountCount()).toBe(1);

    mockUseLesson.mockReturnValue({ lesson: lessonB, isLoading: false, error: null });
    rerender(<PlayerLoader lessonId="lesson_B" />);

    // A same-key prop update would leave the mount effect from firing only once total;
    // a real remount (via key={lesson.lesson_id}) fires it again for the fresh instance.
    expect(getMountCount()).toBe(2);
  });

  it('does NOT remount Player when re-rendering with the same lesson_id', () => {
    mockUseLesson.mockReturnValue({ lesson: mockLessonPackage, isLoading: false, error: null });
    const { rerender } = render(<PlayerLoader lessonId="lesson_mock_1" />);
    expect(getMountCount()).toBe(1);

    rerender(<PlayerLoader lessonId="lesson_mock_1" />);

    expect(getMountCount()).toBe(1);
  });

  it('error state takes priority over loading state', () => {
    mockUseLesson.mockReturnValue({
      lesson: null,
      isLoading: true,
      error: new Error('Network error'),
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    // Error wins — skeleton should NOT be shown when error is set
    expect(screen.getByTestId('lesson-error')).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
  });
});
