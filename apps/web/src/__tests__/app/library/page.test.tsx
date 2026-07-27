import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { getLibraryMock } = vi.hoisted(() => ({ getLibraryMock: vi.fn() }));

vi.mock('@/services/library.service', () => ({
  libraryService: { getLibrary: getLibraryMock },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { LibraryDataFetcher } from '@/app/(dashboard)/library/page';

beforeEach(() => {
  getLibraryMock.mockReset();
});

describe('LibraryDataFetcher (library server component)', () => {
  it('renders LibraryView with the real data on success', async () => {
    getLibraryMock.mockResolvedValue({ ready: [], processing: [], failed: [] });

    render(await LibraryDataFetcher());

    expect(screen.getByText('No lessons found in this category.')).not.toBeNull();
  });

  it('shows a fallback message instead of crashing when the real API call rejects', async () => {
    getLibraryMock.mockRejectedValue(new Error('Library unavailable'));

    render(await LibraryDataFetcher());

    expect(screen.getByText("We couldn't load your library right now.")).not.toBeNull();
  });
});
