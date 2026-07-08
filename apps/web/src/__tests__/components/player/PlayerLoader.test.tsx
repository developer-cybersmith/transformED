import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('@/hooks/useLesson', () => ({
  useLesson: vi.fn(),
}));

// next/dynamic returns the loading component on first render in test env.
// We resolve it to the actual component after controlling the hook state.
vi.mock('next/dynamic', () => ({
  default: (importFn: () => Promise<{ default: React.ComponentType<unknown> }>, opts?: { loading?: () => React.ReactNode }) => {
    // In jsdom, return a stub that renders the loading fallback or a placeholder
    const MockPlayer = ({ lesson }: { lesson: typeof mockLessonPackage }) => (
      <div data-testid="player-stub">{lesson.metadata.title}</div>
    );
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

// ── S1-11: lesson parse error state ──────────────────────────────────────────

describe('PlayerLoader — parse error state', () => {
  it('7a: renders LessonParseErrorState when lesson has empty segments array', () => {
    // Valid JSON returned but fails isValidLessonPackage check (segments.length === 0)
    mockUseLesson.mockReturnValue({
      lesson: {
        ...mockLessonPackage,
        segments: [],
      } as typeof mockLessonPackage,
      isLoading: false,
      error: null,
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-parse-error')).toBeDefined();
    expect(screen.queryByTestId('player-stub')).toBeNull();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
  });

  it('7b: renders LessonParseErrorState when lesson_id is missing', () => {
    mockUseLesson.mockReturnValue({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      lesson: { segments: [{}], metadata: { title: 'x' } } as any,
      isLoading: false,
      error: null,
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-parse-error')).toBeDefined();
  });

  it('7c: does NOT render LessonParseErrorState for a valid lesson package', () => {
    mockUseLesson.mockReturnValue({
      lesson: mockLessonPackage,
      isLoading: false,
      error: null,
    });

    render(<PlayerLoader lessonId="lesson_mock_1" />);

    expect(screen.queryByTestId('lesson-parse-error')).toBeNull();
    expect(screen.getByTestId('player-stub')).toBeDefined();
  });
});
