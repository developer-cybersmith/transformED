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
    const data = { lessons: [] };
    getLibraryMock.mockResolvedValue({ success: true, data, message: 'ok' });

    render(await LibraryDataFetcher());

    expect(screen.getByText(/No lessons yet/i)).not.toBeNull();
  });

  it('shows a fallback message instead of crashing when the response has no data (success: false)', async () => {
    getLibraryMock.mockResolvedValue({ success: false, data: null, message: 'Library unavailable' });

    render(await LibraryDataFetcher());

    expect(screen.getByText("We couldn't load your library right now.")).not.toBeNull();
  });
});
