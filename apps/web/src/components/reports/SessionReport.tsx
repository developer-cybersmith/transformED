'use client';

import Link from 'next/link';
import { useSessionReport } from '@/hooks/useSessionReport';
import { formatCesLabel, formatTeachbackLabel } from '@/lib/utils';

interface SessionReportProps {
  sessionId: string;
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
            {report.quiz_score === null
              ? 'No quiz questions this session'
              : `${Math.round(report.quiz_score * 10) / 10}% correct`}
          </span>
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

      <Link
        href={`/lesson/${report.lesson_id}`}
        className="self-start px-6 py-2.5 rounded-full bg-[var(--accent-secondary)] text-primary text-sm font-semibold hover:brightness-105 transition-all"
      >
        Study Again
      </Link>
    </div>
  );
}
