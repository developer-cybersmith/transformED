import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({
  default: useSWRMock,
}));

const { getLibraryMock } = vi.hoisted(() => ({
  getLibraryMock: vi.fn(),
}));

vi.mock('@/services/library.service', () => ({
  libraryService: { getLibrary: getLibraryMock },
}));

import { useLibrary } from '@/hooks/useLibrary';

beforeEach(() => {
  useSWRMock.mockReset();
  getLibraryMock.mockReset();
  useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: true });
});

describe('useLibrary', () => {
  it('does not retry indefinitely on error', () => {
    renderHook(() => useLibrary());

    expect(useSWRMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.any(Function),
      expect.objectContaining({ shouldRetryOnError: false })
    );
  });

  it('returns the fetched library data and stops loading', async () => {
    const data = { all: [], ready: [], processing: [], failed: [] };
    useSWRMock.mockReturnValue({ data, error: undefined, isLoading: false });

    const { result } = renderHook(() => useLibrary());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(data);
  });

  it('surfaces a fetch error and returns null data', () => {
    const err = new Error('network error');
    useSWRMock.mockReturnValue({ data: undefined, error: err, isLoading: false });

    const { result } = renderHook(() => useLibrary());

    expect(result.current.error).toBe(err);
    expect(result.current.data).toBeNull();
  });
});
