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
    mockUseLesson.mockReturnValue({ lesson: null, isLoading: true, error: null, status: undefined, serverError: null });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('player-skeleton')).toBeDefined();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
    expect(screen.queryByTestId('player-stub')).toBeNull();
  });

  it('renders LessonErrorState when the fetch completes with a null lesson (no explicit error, no status)', () => {
    // A completed fetch (isLoading: false) with no lesson, no error, and no
    // status is treated as an error state, not a skeleton — genuinely unexpected
    // shape, distinct from the real running/failed states covered below.
    mockUseLesson.mockReturnValue({
      lesson: null, isLoading: false, error: null, status: undefined, serverError: null,
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-error')).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
  });

  it('renders a distinct "still generating" state (not the error page) when status is running (S1-7)', () => {
    mockUseLesson.mockReturnValue({
      lesson: null, isLoading: false, error: null, status: 'running', serverError: null,
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-generating')).toBeDefined();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
  });

  it('renders a distinct "still generating" state when status is queued (S1-7)', () => {
    mockUseLesson.mockReturnValue({
      lesson: null, isLoading: false, error: null, status: 'queued', serverError: null,
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-generating')).toBeDefined();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
  });

  it('surfaces the real backend error message when status is failed, instead of the generic message (S1-7)', () => {
    mockUseLesson.mockReturnValue({
      lesson: null, isLoading: false, error: null, status: 'failed', serverError: 'Cost ceiling exceeded',
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    expect(screen.getByTestId('lesson-error')).toBeDefined();
    expect(screen.getByText('Cost ceiling exceeded')).toBeDefined();
    expect(screen.queryByText('This lesson could not be loaded. Please try again.')).toBeNull();
  });

  it('renders LessonErrorState when hook returns an error', () => {
    mockUseLesson.mockReturnValue({
      lesson: null,
      isLoading: false,
      error: new Error('Lesson not found'),
      status: undefined,
      serverError: null,
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
      status: 'ready',
      serverError: null,
    });

    render(<PlayerLoader lessonId="lesson_mock_1" />);

    expect(screen.getByTestId('player-stub')).toBeDefined();
    expect(screen.getByText(mockLessonPackage.metadata.title)).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
    expect(screen.queryByTestId('lesson-error')).toBeNull();
  });

  it('passes the lessonId to useLesson', () => {
    mockUseLesson.mockReturnValue({ lesson: null, isLoading: true, error: null, status: undefined, serverError: null });

    render(<PlayerLoader lessonId="lesson_xyz" />);

    expect(mockUseLesson).toHaveBeenCalledWith('lesson_xyz');
  });

  it('error state takes priority over loading state', () => {
    mockUseLesson.mockReturnValue({
      lesson: null,
      isLoading: true,
      error: new Error('Network error'),
      status: undefined,
      serverError: null,
    });

    render(<PlayerLoader lessonId="lesson_1" />);

    // Error wins — skeleton should NOT be shown when error is set
    expect(screen.getByTestId('lesson-error')).toBeDefined();
    expect(screen.queryByTestId('player-skeleton')).toBeNull();
  });
});
