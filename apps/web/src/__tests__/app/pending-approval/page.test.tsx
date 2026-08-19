import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: vi.fn() }),
}));

import PendingApprovalPage from '@/app/pending-approval/page';

describe('PendingApprovalPage', () => {
  it('clips its decorative ambient-glow background instead of letting it create page-level horizontal overflow (Story 2-49/S3-08)', () => {
    // Story 2-49: found live at 768px that this page's two absolutely-positioned
    // decorative glow divs (top-[-10%] left-[-10%] w-[50%] h-[50%], etc.) made the
    // page genuinely horizontally scrollable, unlike the sibling signin/signup
    // pages which already wrap the identical pattern in `overflow-hidden`.
    render(<PendingApprovalPage />);

    const root = screen.getByText(/you're on the list/i).closest('div[class*="min-h-screen"]');
    expect(root).not.toBeNull();
    expect(root!.className).toMatch(/overflow-hidden/);
  });
});
