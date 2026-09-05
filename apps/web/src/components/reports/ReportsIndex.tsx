'use client';

import Link from 'next/link';
import { useSessionReports } from '@/hooks/useSessionReports';
import { cesScoreColor, formatCesLabel } from '@/lib/utils';
import type { SessionSummary } from '@/types/assessment';

// Story 2-58 (BR-7): Sidebar.tsx's "Reports" nav link has pointed at /reports
// since it was first built, with no route behind it -- 404 from the
// beginning. This page (and GET /assessment/sessions behind it) is the fix.
// Standalone page, no dashboard shell -- matches the existing convention for
// /reports/[sessionId] (SessionReport.tsx), which is also sidebar-less.

function formatSessionDate(isoString: string | null): string | null {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

function LoadingState() {
  return (
    <div
      data-testid="reports-index-loading"
      className="flex flex-col gap-4 w-full max-w-2xl mx-auto pt-8 pb-12 px-4 sm:px-8 lg:px-12 animate-pulse"
    >
      <div className="h-7 w-40 rounded bg-neutral-100" />
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="h-20 rounded-2xl bg-neutral-100" />
      ))}
    </div>
  );
}

function ErrorState() {
  return (
    <div
      data-testid="reports-index-error"
      className="flex flex-col items-center justify-center max-w-2xl mx-auto pt-24 pb-24 px-4 sm:px-8 lg:px-12 text-center gap-6"
    >
      <p className="text-neutral-500">Your reports aren&apos;t available right now.</p>
      <Link
        href="/dashboard"
        className="px-6 py-2.5 rounded-full bg-[var(--accent-secondary)] text-primary text-sm font-semibold hover:brightness-105 transition-all"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      data-testid="reports-index-empty"
      className="flex flex-col items-center justify-center max-w-2xl mx-auto pt-24 pb-24 px-4 sm:px-8 lg:px-12 text-center gap-6"
    >
      <p className="text-neutral-500">
        No session reports yet — finish a lesson to see one here.
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

function SessionCard({ session }: { session: SessionSummary }) {
  const date = formatSessionDate(session.started_at);
  return (
    <Link
      href={`/reports/${session.session_id}`}
      data-testid={`session-card-${session.session_id}`}
      className="flex items-center justify-between gap-4 p-5 rounded-2xl bg-white border border-neutral-100
                 shadow-sm hover:shadow-md hover:border-neutral-200 transition-all"
    >
      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-neutral-900 font-medium truncate">
          {session.lesson_title ?? 'Untitled Lesson'}
        </span>
        <span className="text-neutral-500 text-sm">
          {session.tier_label}
          {date && ` · ${date}`}
          {!session.completed && ' · In progress'}
        </span>
      </div>
      <div className="flex flex-col items-end gap-0.5 flex-shrink-0">
        <span className={`font-medium text-sm ${cesScoreColor(session.ces_score)}`}>
          {formatCesLabel(session.ces_score)}
        </span>
        {session.ces_score !== null && (
          <span className="text-neutral-400 text-xs">{Math.round(session.ces_score)}/100</span>
        )}
      </div>
    </Link>
  );
}

export function ReportsIndex() {
  const { sessions, isLoading, error } = useSessionReports();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState />;
  if (sessions.length === 0) return <EmptyState />;

  return (
    <div
      data-testid="reports-index-root"
      className="flex flex-col gap-6 w-full max-w-2xl mx-auto pt-8 pb-12 px-4 sm:px-8 lg:px-12"
    >
      <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight">
        Reports
      </h2>
      <div className="flex flex-col gap-3">
        {sessions.map((session) => (
          <SessionCard key={session.session_id} session={session} />
        ))}
      </div>
    </div>
  );
}
