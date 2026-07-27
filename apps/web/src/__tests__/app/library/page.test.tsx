import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { useLibraryMock } = vi.hoisted(() => ({ useLibraryMock: vi.fn() }));

vi.mock('@/hooks/useLibrary', () => ({
  useLibrary: useLibraryMock,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import LibraryPage from '@/app/(dashboard)/library/page';

beforeEach(() => {
  useLibraryMock.mockReset();
});

describe('LibraryPage', () => {
  it('shows a loading state while the real fetch is in flight', () => {
    useLibraryMock.mockReturnValue({ data: null, error: undefined, isLoading: true });

    render(<LibraryPage />);

    expect(screen.getByText('Loading intelligence...')).not.toBeNull();
  });

  it('renders LibraryView with the real data on success', () => {
    useLibraryMock.mockReturnValue({
      data: { all: [], ready: [], processing: [], failed: [] },
      error: undefined,
      isLoading: false,
    });

    render(<LibraryPage />);

    expect(screen.getByText('No lessons found in this category.')).not.toBeNull();
  });

  it('shows a fallback message instead of crashing when the real API call fails', () => {
    useLibraryMock.mockReturnValue({
      data: null,
      error: new Error('Library unavailable'),
      isLoading: false,
    });

    render(<LibraryPage />);

    expect(screen.getByText("We couldn't load your library right now.")).not.toBeNull();
  });
});
