import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SessionReport } from '@/components/reports/SessionReport';

const { useSessionReportMock } = vi.hoisted(() => ({
  useSessionReportMock: vi.fn(),
}));

vi.mock('@/hooks/useSessionReport', () => ({
  useSessionReport: useSessionReportMock,
}));

// AttentionChart (Story 2-46/S3-05) is tested on its own in AttentionChart.test.tsx --
// mocked here so these tests check SessionReport's OWN behavior (does it pass the
// right props, does it mount/omit conditionally) without pulling in real recharts.
vi.mock('@/components/reports/AttentionChart', () => ({
  AttentionChart: ({ timeline }: { timeline: unknown }) => (
    <div data-testid="mock-attention-chart" data-has-timeline={timeline !== null} />
  ),
}));

const FULL_REPORT = {
  session_id: 'sess_1',
  user_id: 'user_1',
  lesson_id: 'lesson_1',
  ces_score: 85,
  ces_breakdown: { quiz: 28.0, teachback: 20.0, behavioral: 0.0, head_pose: 0.0, blink: 0.0 },
  interventions_count: 2,
  quiz_score: 78.5,
  teachback_score: 90,
  duration_minutes: 42,
  completed_at: '2026-07-04T10:00:00Z',
  tier: 'T2' as const,
  tier_label: 'Standard',
  quiz_total_questions: 4,
  quiz_correct_count: 3,
  quiz_accuracy_label: 'Strong' as const,
  learner_dna_snapshot: null,
  ces_timeline: [{ minute: 0, ces: 60 }, { minute: 1, ces: 75 }],
  intervention_events: [{ minute: 1, type: 'distraction' }],
  teachback_details: null,
};

// Story 2-48 (S3-06) fixtures — per-segment teach-back detail.
const TEACHBACK_DETAILS_FIXTURE = [
  {
    segment_id: 'seg_001',
    score: 85,
    feedback_praise: 'Great explanation of mitochondria.',
    feedback_correction: null,
    concepts_hit: ['mitochondria', 'ATP'],
    concepts_missed: [],
    attempt_number: 1,
  },
  {
    segment_id: 'seg_002',
    score: 45,
    feedback_praise: null,
    feedback_correction: 'Remember that photosynthesis happens in the chloroplast, not the nucleus.',
    concepts_hit: [],
    concepts_missed: ['chloroplast', 'photosynthesis location'],
    attempt_number: 1,
  },
];

beforeEach(() => {
  useSessionReportMock.mockReset();
});

describe('SessionReport', () => {
  it('shows a loading state while the report is in flight', () => {
    useSessionReportMock.mockReturnValue({ report: null, isLoading: true, error: undefined });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByTestId('session-report-loading')).not.toBeNull();
  });

  it('shows an error/empty state on fetch failure, with a link back to the dashboard', () => {
    useSessionReportMock.mockReturnValue({ report: null, isLoading: false, error: new Error('404') });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByTestId('session-report-error')).not.toBeNull();
    const link = screen.getByRole('link', { name: /dashboard/i });
    expect(link.getAttribute('href')).toBe('/dashboard');
  });

  it('renders quiz accuracy as absolute counts + a descriptive label, never the raw quiz_score percentage (S2-10 review fix)', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByText('3 / 4 correct')).not.toBeNull();
    expect(screen.getByText('Strong')).not.toBeNull();
    expect(container.textContent).not.toMatch(/78(\.5)?%/);
  });

  it('shows a friendly fallback when quiz_accuracy_label is null (zero questions attempted)', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, quiz_total_questions: 0, quiz_correct_count: 0, quiz_accuracy_label: null },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByText(/No quiz questions this session/i)).not.toBeNull();
  });

  it('shows the tier_label on the report (S2-10)', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).toMatch(/Standard/);
  });

  it('omits the DNA snapshot section entirely when learner_dna_snapshot is null (S2-10)', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, learner_dna_snapshot: null },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.queryByTestId('dna-snapshot-section')).toBeNull();
  });

  it('shows all 9 dimension labels when learner_dna_snapshot is present (S2-10)', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        learner_dna_snapshot: {
          dimension_labels: {
            pattern_recognition: 'Proficient',
            logical_deduction: 'Developing',
            processing_speed: 'Emerging',
            frustration_tolerance: 'Beginning',
            persistence: 'Proficient',
            help_seeking: 'Developing',
            goal_orientation: 'Emerging',
            curiosity_index: 'Beginning',
            study_independence: 'Proficient',
          },
          growth_labels: {
            pattern_recognition: 'Improving',
            logical_deduction: null,
            processing_speed: 'Stable',
            frustration_tolerance: 'Needs Attention',
            persistence: null,
            help_seeking: 'Improving',
            goal_orientation: 'Stable',
            curiosity_index: 'Needs Attention',
            study_independence: null,
          },
        },
      },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByTestId('dna-snapshot-section')).not.toBeNull();
    expect(screen.getByText('Pattern Recognition')).not.toBeNull();
    expect(screen.getByText('Study Independence')).not.toBeNull();
    // A dimension with a non-null growth label shows its indicator...
    expect(screen.getByTestId('dna-growth-pattern_recognition')).not.toBeNull();
    // ...while a dimension with a null growth label shows none, without
    // affecting whether other dimensions' indicators render.
    expect(screen.queryByTestId('dna-growth-logical_deduction')).toBeNull();
    expect(screen.getByTestId('dna-growth-processing_speed')).not.toBeNull();
  });

  it('never renders a raw DNA dimension score or delta number anywhere (S2-10)', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        learner_dna_snapshot: {
          dimension_labels: {
            pattern_recognition: 'Proficient', logical_deduction: 'Developing',
            processing_speed: 'Emerging', frustration_tolerance: 'Beginning',
            persistence: 'Proficient', help_seeking: 'Developing',
            goal_orientation: 'Emerging', curiosity_index: 'Beginning',
            study_independence: 'Proficient',
          },
          growth_labels: {
            pattern_recognition: 'Improving', logical_deduction: null,
            processing_speed: 'Stable', frustration_tolerance: 'Needs Attention',
            persistence: null, help_seeking: 'Improving',
            goal_orientation: 'Stable', curiosity_index: 'Needs Attention',
            study_independence: null,
          },
        },
      },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    // Scoped to the DNA section only -- the rest of the report legitimately
    // shows numbers (quiz counts, minutes studied, etc.), just not DNA scores.
    const dnaSection = screen.getByTestId('dna-snapshot-section');
    expect(dnaSection.textContent).not.toMatch(/\b\d{1,3}(\.\d+)?\b/);
  });

  it('falls back gracefully instead of rendering "undefined" for an unrecognized growth label (review fix)', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        learner_dna_snapshot: {
          dimension_labels: {
            pattern_recognition: 'Proficient', logical_deduction: 'Developing',
            processing_speed: 'Emerging', frustration_tolerance: 'Beginning',
            persistence: 'Proficient', help_seeking: 'Developing',
            goal_orientation: 'Emerging', curiosity_index: 'Beginning',
            study_independence: 'Proficient',
          },
          growth_labels: {
            // Simulates a backend value outside the known union (e.g. a
            // legacy/renamed label) reaching the frontend unchanged.
            pattern_recognition: 'Declining' as unknown as 'Improving',
            logical_deduction: null, processing_speed: 'Stable',
            frustration_tolerance: 'Needs Attention', persistence: null,
            help_seeking: 'Improving', goal_orientation: 'Stable',
            curiosity_index: 'Needs Attention', study_independence: null,
          },
        },
      },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    // GROWTH_INDICATORS[growth] evaluates to undefined for an unrecognized
    // value, and React silently renders undefined as nothing (not the literal
    // text "undefined") -- the real defect is a blank icon with a stale
    // aria-label/title, not visible "undefined" text.
    const indicator = screen.getByTestId('dna-growth-pattern_recognition');
    expect(indicator.textContent).not.toBe('');
  });

  it('never renders a raw CES or teach-back number — only descriptive labels', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    // The raw ces_score (85) and teachback_score (90) must never appear as visible numbers.
    expect(screen.queryByText('85')).toBeNull();
    expect(screen.queryByText('90')).toBeNull();
    expect(container.textContent).toMatch(/Highly Engaged/);
    expect(container.textContent).toMatch(/Strong grasp/);
  });

  it('shows friendly messaging when quiz_score and teachback_score are both null (zero-attempt session)', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        quiz_score: null,
        teachback_score: null,
        quiz_total_questions: 0,
        quiz_correct_count: 0,
        quiz_accuracy_label: null,
      },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByText(/No quiz questions this session/i)).not.toBeNull();
    expect(screen.getByText(/No teach-back this session/i)).not.toBeNull();
  });

  it('"Study Again" links to /lesson/{lesson_id} from the report response', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    render(<SessionReport sessionId="sess_1" />);

    const link = screen.getByRole('link', { name: /study again/i });
    expect(link.getAttribute('href')).toBe('/lesson/lesson_1');
  });

  it('renders engagement summary (duration, interventions) without dumping raw field names', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).toMatch(/42/);
    expect(container.textContent).not.toMatch(/duration_minutes/);
    expect(container.textContent).not.toMatch(/interventions_count/);
  });

  it('never renders "NaN minutes studied" for a non-finite duration_minutes', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, duration_minutes: NaN },
      isLoading: false,
      error: undefined,
    });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).not.toMatch(/NaN/);
  });

  it('never renders literal "Invalid Date" for a malformed completed_at', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, completed_at: 'not-a-real-date' },
      isLoading: false,
      error: undefined,
    });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).not.toMatch(/Invalid Date/);
  });

  it('mounts AttentionChart after the stat grid and before the DNA snapshot when ces_timeline is present (Story 2-46/S3-05)', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        learner_dna_snapshot: {
          dimension_labels: Object.fromEntries(
            ['pattern_recognition', 'logical_deduction', 'processing_speed', 'frustration_tolerance',
             'persistence', 'help_seeking', 'goal_orientation', 'curiosity_index', 'study_independence']
              .map((d) => [d, 'Proficient'])
          ),
          growth_labels: Object.fromEntries(
            ['pattern_recognition', 'logical_deduction', 'processing_speed', 'frustration_tolerance',
             'persistence', 'help_seeking', 'goal_orientation', 'curiosity_index', 'study_independence']
              .map((d) => [d, null])
          ),
        },
      },
      isLoading: false,
      error: undefined,
    });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    const chart = screen.getByTestId('mock-attention-chart');
    expect(chart.getAttribute('data-has-timeline')).toBe('true');

    const dna = screen.getByTestId('dna-snapshot-section');
    const chartIndex = Array.from(container.querySelectorAll('*')).indexOf(chart);
    const dnaIndex = Array.from(container.querySelectorAll('*')).indexOf(dna);
    expect(chartIndex).toBeGreaterThan(-1);
    expect(chartIndex).toBeLessThan(dnaIndex);
  });

  it('omits AttentionChart entirely (not an empty card) when ces_timeline is null', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, ces_timeline: null, intervention_events: null },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.queryByTestId('mock-attention-chart')).toBeNull();
  });

  // ── Story 2-48 (S3-06) — teach-back summary detail ──────────────────────────

  it('omits the teach-back detail section entirely when teachback_details is null', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, teachback_details: null },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.queryByTestId('teachback-detail-section')).toBeNull();
  });

  it('omits the teach-back detail section entirely when teachback_details is an empty array', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, teachback_details: [] },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.queryByTestId('teachback-detail-section')).toBeNull();
  });

  it('renders one entry per segment, in array order, labelled by position not raw segment_id', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, teachback_details: TEACHBACK_DETAILS_FIXTURE },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    const section = screen.getByTestId('teachback-detail-section');
    expect(section.textContent).toMatch(/Segment 1/);
    expect(section.textContent).toMatch(/Segment 2/);
    expect(section.textContent).not.toMatch(/seg_001/);
    expect(section.textContent).not.toMatch(/seg_002/);
  });

  it('buckets each entry\'s score through formatTeachbackLabel — never the raw number', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, teachback_details: TEACHBACK_DETAILS_FIXTURE },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    const section = screen.getByTestId('teachback-detail-section');
    expect(section.textContent).toMatch(/Strong grasp/); // 85 -> Strong grasp
    expect(section.textContent).toMatch(/Needs another look/); // 45 -> Needs another look
    // Raw scores (85, 45) must never appear as bare numbers anywhere in the section.
    expect(section.textContent).not.toMatch(/\b85\b/);
    expect(section.textContent).not.toMatch(/\b45\b/);
  });

  it('renders feedback_praise and feedback_correction independently — each omitted only when null, not replaced by placeholder text', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, teachback_details: TEACHBACK_DETAILS_FIXTURE },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    const section = screen.getByTestId('teachback-detail-section');
    expect(section.textContent).toMatch(/Great explanation of mitochondria\./);
    expect(section.textContent).toMatch(
      /Remember that photosynthesis happens in the chloroplast, not the nucleus\./
    );
    expect(section.textContent).not.toMatch(/No feedback/i);
  });

  it('renders concept chips only when the array is non-empty', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, teachback_details: TEACHBACK_DETAILS_FIXTURE },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    // Segment 1: concepts_hit populated, concepts_missed empty.
    expect(screen.getByTestId('teachback-concepts-hit-0')).not.toBeNull();
    expect(screen.queryByTestId('teachback-concepts-missed-0')).toBeNull();
    // Segment 2: concepts_hit empty, concepts_missed populated.
    expect(screen.queryByTestId('teachback-concepts-hit-1')).toBeNull();
    expect(screen.getByTestId('teachback-concepts-missed-1')).not.toBeNull();

    const section = screen.getByTestId('teachback-detail-section');
    expect(section.textContent).toMatch(/mitochondria/);
    expect(section.textContent).toMatch(/chloroplast/);
  });

  it('mounts the teach-back detail section after AttentionChart and before the DNA snapshot', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        teachback_details: TEACHBACK_DETAILS_FIXTURE,
        learner_dna_snapshot: {
          dimension_labels: Object.fromEntries(
            ['pattern_recognition', 'logical_deduction', 'processing_speed', 'frustration_tolerance',
             'persistence', 'help_seeking', 'goal_orientation', 'curiosity_index', 'study_independence']
              .map((d) => [d, 'Proficient'])
          ),
          growth_labels: Object.fromEntries(
            ['pattern_recognition', 'logical_deduction', 'processing_speed', 'frustration_tolerance',
             'persistence', 'help_seeking', 'goal_orientation', 'curiosity_index', 'study_independence']
              .map((d) => [d, null])
          ),
        },
      },
      isLoading: false,
      error: undefined,
    });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    const chart = screen.getByTestId('mock-attention-chart');
    const detail = screen.getByTestId('teachback-detail-section');
    const dna = screen.getByTestId('dna-snapshot-section');
    const all = Array.from(container.querySelectorAll('*'));
    const chartIndex = all.indexOf(chart);
    const detailIndex = all.indexOf(detail);
    const dnaIndex = all.indexOf(dna);
    expect(chartIndex).toBeLessThan(detailIndex);
    expect(detailIndex).toBeLessThan(dnaIndex);
  });

  it('does not crash on a null per-attempt score (real, reachable shape — teachback_attempts.score has no NOT NULL constraint) and still renders a descriptive label', () => {
    useSessionReportMock.mockReturnValue({
      report: {
        ...FULL_REPORT,
        teachback_details: [
          {
            segment_id: 'seg_003',
            score: null,
            feedback_praise: null,
            feedback_correction: null,
            concepts_hit: [],
            concepts_missed: [],
            attempt_number: 1,
          },
        ],
      },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    const section = screen.getByTestId('teachback-detail-section');
    expect(section.textContent).toMatch(/Segment 1/);
    // formatTeachbackLabel(null) -> "No teach-back this session" -- reused as-is, not a crash.
    expect(section.textContent).toMatch(/No teach-back this session/);
  });
});
