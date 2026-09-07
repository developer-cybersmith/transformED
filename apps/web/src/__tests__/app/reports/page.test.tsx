import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { reportsIndexMock } = vi.hoisted(() => ({
  reportsIndexMock: vi.fn(),
}));

vi.mock('@/components/reports/ReportsIndex', () => ({
  ReportsIndex: () => {
    reportsIndexMock();
    return <div data-testid="reports-index-stub" />;
  },
}));

import ReportsIndexPage from '@/app/reports/page';

beforeEach(() => {
  reportsIndexMock.mockReset();
});

describe('ReportsIndexPage — Story 2-58 / BR-7', () => {
  it('renders ReportsIndex — the route the previously-dead /reports nav link now resolves to', () => {
    render(<ReportsIndexPage />);

    expect(reportsIndexMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('reports-index-stub')).not.toBeNull();
  });
});
