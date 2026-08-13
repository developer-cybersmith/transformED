import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/react';
import { AttentionChart } from '@/components/reports/AttentionChart';

// jsdom has no matchMedia; only this component's useMediaQuery consumes it so
// far, so the mock lives here rather than in the shared global setup.
function mockMatchMedia(matches: boolean) {
  const listeners: Array<() => void> = [];
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    addEventListener: (_: string, cb: () => void) => listeners.push(cb),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

const TIMELINE = [
  { minute: 0, ces: 30 },
  { minute: 1, ces: 55 },
  { minute: 2, ces: 80 },
];

describe('AttentionChart', () => {
  beforeEach(() => {
    mockMatchMedia(false); // default: desktop viewport
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the empty-state message when timeline is null', () => {
    const { getByTestId, queryByTestId } = render(
      <AttentionChart timeline={null} interventions={null} />
    );
    expect(getByTestId('attention-chart-empty').textContent).toContain(
      'Not enough data for a timeline yet'
    );
    expect(queryByTestId('attention-chart')).toBeNull();
  });

  it('renders the empty-state message when timeline has fewer than 2 points', () => {
    const { getByTestId, queryByTestId } = render(
      <AttentionChart timeline={[{ minute: 0, ces: 50 }]} interventions={null} />
    );
    expect(getByTestId('attention-chart-empty').textContent).toContain(
      'Not enough data for a timeline yet'
    );
    expect(queryByTestId('attention-chart')).toBeNull();
  });

  it('renders the chart when timeline has 2+ points', () => {
    const { getByTestId, container } = render(
      <AttentionChart timeline={TIMELINE} interventions={null} />
    );
    expect(getByTestId('attention-chart')).toBeTruthy();
    expect(container.querySelector('.recharts-area')).toBeTruthy();
  });

  it('Y-axis renders only Low/Medium/High labels — never a raw CES number', () => {
    const { container } = render(
      <AttentionChart timeline={TIMELINE} interventions={null} />
    );
    const yAxisText = Array.from(
      container.querySelectorAll('.recharts-yAxis text')
    ).map((el) => el.textContent);

    expect(yAxisText.length).toBeGreaterThan(0);
    for (const text of yAxisText) {
      expect(['Low', 'Medium', 'High']).toContain(text);
    }
    // Belt-and-suspenders: no decimal-looking CES value anywhere in the Y-axis tick group.
    const yAxisGroup = container.querySelector('.recharts-yAxis');
    expect(yAxisGroup?.textContent).not.toMatch(/\d\.\d/);
  });

  it('renders a vertical reference line for each intervention event, distinguishable by type', () => {
    const { container } = render(
      <AttentionChart
        timeline={TIMELINE}
        interventions={[
          { minute: 1, type: 'distraction' },
          { minute: 2, type: 'fatigue' },
        ]}
      />
    );
    const distraction = container.querySelector(
      '[data-testid="intervention-marker-distraction"]'
    );
    const fatigue = container.querySelector('[data-testid="intervention-marker-fatigue"]');
    expect(distraction).toBeTruthy();
    expect(fatigue).toBeTruthy();
  });

  it('renders no intervention markers when interventions is null', () => {
    const { container } = render(
      <AttentionChart timeline={TIMELINE} interventions={null} />
    );
    expect(container.querySelectorAll('[data-testid^="intervention-marker-"]').length).toBe(0);
  });

  it('shows a recency caption reflecting the actual number of points, never implying full-session coverage', () => {
    const { getByTestId } = render(
      <AttentionChart timeline={TIMELINE} interventions={null} />
    );
    const caption = getByTestId('attention-chart-recency-caption');
    expect(caption.textContent).toContain('3');
    expect(caption.textContent?.toLowerCase()).not.toContain('whole session');
    expect(caption.textContent?.toLowerCase()).not.toContain('full session');
  });

  it('collapses to a simpler view below the sm breakpoint — no X-axis tick labels, reduced height', () => {
    mockMatchMedia(true); // mobile viewport
    const { container } = render(
      <AttentionChart timeline={TIMELINE} interventions={null} />
    );
    const xAxisText = container.querySelectorAll('.recharts-xAxis text');
    expect(xAxisText.length).toBe(0);
  });

  it('shows X-axis tick labels at/above the sm breakpoint', () => {
    mockMatchMedia(false); // desktop viewport
    const { container } = render(
      <AttentionChart timeline={TIMELINE} interventions={null} />
    );
    const xAxisText = container.querySelectorAll('.recharts-xAxis text');
    expect(xAxisText.length).toBeGreaterThan(0);
  });
});
