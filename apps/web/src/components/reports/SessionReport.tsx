'use client';

import Link from 'next/link';
import { useSessionReport } from '@/hooks/useSessionReport';
import { formatCesLabel, formatTeachbackLabel } from '@/lib/utils';
import type { DnaDimension, LearnerDnaSnapshot } from '@/types/assessment';

interface SessionReportProps {
  sessionId: string;
}

// Human-readable dimension names — never render the raw snake_case key (S2-10).
const DIMENSION_DISPLAY_NAMES: Record<DnaDimension, string> = {
  pattern_recognition: 'Pattern Recognition',
  logical_deduction: 'Logical Deduction',
  processing_speed: 'Processing Speed',
  frustration_tolerance: 'Frustration Tolerance',
  persistence: 'Persistence',
  help_seeking: 'Help-Seeking',
  goal_orientation: 'Goal Orientation',
  curiosity_index: 'Curiosity',
  study_independence: 'Study Independence',
};

const DIMENSION_ORDER = Object.keys(DIMENSION_DISPLAY_NAMES) as DnaDimension[];

const GROWTH_INDICATORS: Record<'Improving' | 'Stable' | 'Needs Attention', string> = {
  Improving: '↑',
  Stable: '→',
  'Needs Attention': '↓',
};

function DnaSnapshotSection({ snapshot }: { snapshot: LearnerDnaSnapshot }) {
  return (
    <div
      data-testid="dna-snapshot-section"
      className="flex flex-col gap-3 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm"
    >
      <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
        Learner DNA Snapshot
      </span>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
        {DIMENSION_ORDER.map((dim) => {
          const growth = snapshot.growth_labels[dim];
          return (
            <div key={dim} className="flex items-center justify-between gap-2">
              <span className="text-neutral-700 text-sm">{DIMENSION_DISPLAY_NAMES[dim]}</span>
              <span className="text-neutral-900 text-sm font-medium flex items-center gap-1.5">
                {snapshot.dimension_labels[dim]}
                {growth !== null && (
                  <span data-testid={`dna-growth-${dim}`} aria-label={growth} title={growth}>
                    {GROWTH_INDICATORS[growth]}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div
      data-testid="session-report-loading"
      className="flex flex-col gap-8 w-full max-w-2xl mx-auto pt-8 pb-12 animate-pulse"
    >
      <div className="flex flex-col gap-2">
        <div className="h-7 w-48 rounded bg-neutral-100" />
        <div className="h-4 w-32 rounded bg-neutral-100" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 rounded-2xl bg-neutral-100" />
        ))}
      </div>
    </div>
  );
}

function ErrorState() {
  return (
    <div
      data-testid="session-report-error"
      className="flex flex-col items-center justify-center max-w-2xl mx-auto pt-24 pb-24 text-center gap-6"
    >
      <p className="text-neutral-500">
        This session report isn&apos;t available right now.
      </p>
      <Link
        href="/dashboard"
        className="px-6 py-2.5 rounded-full bg-[var(--accent-secondary)] text-primary text-sm font-semibold hover:brightness-105 transition-all"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}

function formatDuration(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes < 0) return 'Unknown study time';
  const whole = Math.round(minutes);
  return `${whole} minute${whole === 1 ? '' : 's'} studied`;
}

function formatInterventions(count: number): string {
  return `${count} focus check-in${count === 1 ? '' : 's'}`;
}

function formatCompletedAt(isoString: string): string | null {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function SessionReport({ sessionId }: SessionReportProps) {
  const { report, isLoading, error } = useSessionReport(sessionId);

  if (isLoading) return <LoadingState />;
  if (error || !report) return <ErrorState />;

  return (
    <div className="flex flex-col gap-8 w-full max-w-2xl mx-auto pt-8 pb-12">
      <div>
        <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight">
          Session Report
        </h2>
        <p className="text-neutral-500 mt-1">
          {report.tier_label} Session
        </p>
        {report.completed_at && formatCompletedAt(report.completed_at) && (
          <p className="text-neutral-500 mt-1">
            {formatCompletedAt(report.completed_at)}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm">
          <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
            Quiz Accuracy
          </span>
          <span className="text-neutral-900 font-medium text-lg">
            {report.quiz_accuracy_label === null
              ? 'No quiz questions this session'
              : `${report.quiz_correct_count} / ${report.quiz_total_questions} correct`}
          </span>
          {report.quiz_accuracy_label !== null && (
            <span className="text-neutral-500 text-sm">{report.quiz_accuracy_label}</span>
          )}
        </div>

        <div className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm">
          <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
            Teach-Back
          </span>
          <span className="text-neutral-900 font-medium text-lg">
            {formatTeachbackLabel(report.teachback_score)}
          </span>
        </div>

        <div className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm">
          <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
            Focus
          </span>
          <span className="text-neutral-900 font-medium text-lg">
            {formatCesLabel(report.ces_score)}
          </span>
        </div>

        <div className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm">
          <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
            Engagement
          </span>
          <span className="text-neutral-900 font-medium text-lg">
            {formatDuration(report.duration_minutes)}
          </span>
          <span className="text-neutral-500 text-sm">
            {formatInterventions(report.interventions_count)}
          </span>
        </div>
      </div>

      {report.learner_dna_snapshot && (
        <DnaSnapshotSection snapshot={report.learner_dna_snapshot} />
      )}

      <Link
        href={`/lesson/${report.lesson_id}`}
        className="self-start px-6 py-2.5 rounded-full bg-[var(--accent-secondary)] text-primary text-sm font-semibold hover:brightness-105 transition-all"
      >
        Study Again
      </Link>
    </div>
  );
}
