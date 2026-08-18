import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QuickActions } from '@/components/dashboard/sections/QuickActions';

/**
 * Story 2-47 (S4-06) review fix: the "My Library" -> "My Books" card rename
 * (title, description, icon, href all changed) previously had zero test
 * coverage anywhere in the repo. This covers the rename directly, so a
 * regression (e.g. a bad merge restoring the old Library href) fails CI
 * instead of passing silently.
 */
describe('QuickActions', () => {
  it('renders the Upload PDF card pointing at /upload', () => {
    render(<QuickActions />);

    const link = screen.getByRole('link', { name: /upload pdf/i });
    expect(link.getAttribute('href')).toBe('/upload');
  });

  it('renders "My Books" (not "My Library"), pointing at /books', () => {
    render(<QuickActions />);

    const link = screen.getByRole('link', { name: /my books/i });
    expect(link.getAttribute('href')).toBe('/books');
    expect(screen.queryByText(/my library/i)).toBeNull();
  });

  it('describes the Books card as browsing books/chapters, not the retired Library framing', () => {
    render(<QuickActions />);

    expect(screen.getByText(/browse your uploaded books and chapters/i)).not.toBeNull();
  });

  it('renders exactly two action cards (Upload PDF, My Books) — no stray "Reports" or "Library" card', () => {
    render(<QuickActions />);

    expect(screen.getAllByRole('link')).toHaveLength(2);
  });
});
