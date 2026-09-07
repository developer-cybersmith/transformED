'use client';

import Link from 'next/link';
import { CheckCircle2, Clock3, Inbox, AlertCircle } from 'lucide-react';
import { useSessionReports } from '@/hooks/useSessionReports';
import { cesScoreColor, formatCesLabel } from '@/lib/utils';
import type { SessionSummary } from '@/types/assessment';

// Story 2-58 (BR-7): Sidebar.tsx's "Reports" nav link has pointed at /reports
// since it was first built, with no route behind it -- 404 from the
// beginning. This page (and GET /assessment/sessions behind it) is the fix.
// Story 2-59 (BR-8): widened from a single narrow column into a full-width,
// block-divided layout (summary row + card grid) per direct user feedback.
// Standalone page, no dashboard shell -- matches the existing convention for
// /reports/[sessionId] (SessionReport.tsx), which is also sidebar-less.

const BLOCK_CLASS = 'rounded-2xl bg-white border border-neutral-100 shadow-sm';

// D161: `toLocaleDateString(undefined, ...)` uses the RUNTIME's default locale --
// SSR (Node) and the browser can disagree (e.g. Node defaults to en-US, a
// browser set to en-GB/en-IN formats dates differently), producing a real
// hydration mismatch in production for any user whose browser locale differs
// from the server's. Pinned to 'en-US' explicitly so server and client always
// agree, regardless of the visitor's own locale setting.
function formatSessionDate(isoString: string | null): string | null {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString('en-US', { dateStyle: 'medium' });
}

function LoadingState() {
  return (
    <div
      data-testid="reports-index-loading"
      className="flex flex-col gap-6 w-full max-w-6xl mx-auto pt-8 pb-16 px-4 sm:px-8 lg:px-12 animate-pulse"
    >
      <div className="h-7 w-40 rounded bg-neutral-100" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-28 rounded-2xl bg-neutral-100" />
        ))}
      </div>
    </div>
  );
}

function ErrorState() {
  return (
    <div
      data-testid="reports-index-error"
      className="flex flex-col items-center justify-center max-w-2xl mx-auto pt-24 pb-24 px-4 sm:px-8 lg:px-12 text-center gap-6"
    >
      <AlertCircle className="w-10 h-10 text-neutral-300" />
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
      <Inbox className="w-10 h-10 text-neutral-300" />
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

// Story 2-59 (BR-8): a quick summary block above the grid — counts derived
// client-side from the already-fetched list, no new network call.
function SummaryBlock({ sessions }: { sessions: SessionSummary[] }) {
  const completedCount = sessions.filter((s) => s.completed).length;
  const inProgressCount = sessions.length - completedCount;

  return (
    <div className={`grid grid-cols-2 sm:grid-cols-3 gap-4`}>
      <div className={`flex flex-col gap-1 p-5 ${BLOCK_CLASS}`}>
        <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
          Total Sessions
        </span>
        <span className="text-neutral-900 font-semibold text-2xl">{sessions.length}</span>
      </div>
      <div className={`flex flex-col gap-1 p-5 ${BLOCK_CLASS}`}>
        <span className="flex items-center gap-1.5 text-xs font-medium text-neutral-500 uppercase tracking-wider">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
          Completed
        </span>
        <span className="text-neutral-900 font-semibold text-2xl">{completedCount}</span>
      </div>
      <div className={`hidden sm:flex flex-col gap-1 p-5 ${BLOCK_CLASS}`}>
        <span className="flex items-center gap-1.5 text-xs font-medium text-neutral-500 uppercase tracking-wider">
          <Clock3 className="w-3.5 h-3.5 text-amber-600" />
          In Progress
        </span>
        <span className="text-neutral-900 font-semibold text-2xl">{inProgressCount}</span>
      </div>
    </div>
  );
}

function SessionCard({ session }: { session: SessionSummary }) {
  const date = formatSessionDate(session.started_at);
  return (
    <Link
      href={`/reports/${session.session_id}`}
      data-testid={`session-card-${session.session_id}`}
      className={`flex flex-col gap-3 p-5 ${BLOCK_CLASS} hover:shadow-md hover:border-neutral-200 transition-all`}
    >
      <div className="flex items-start justify-between gap-3">
        <div
          className={`flex items-center justify-center w-9 h-9 rounded-xl shrink-0 ${
            session.completed ? 'bg-emerald-50' : 'bg-amber-50'
          }`}
        >
          {session.completed ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
          ) : (
            <Clock3 className="w-4 h-4 text-amber-600" />
          )}
        </div>
        <span
          className={`text-xs font-medium px-2 py-0.5 rounded-full ${
            session.completed ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
          }`}
        >
          {session.completed ? 'Completed' : 'In progress'}
        </span>
      </div>

      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-neutral-900 font-medium leading-snug">
          {session.lesson_title ?? 'Untitled Lesson'}
        </span>
        <span className="text-neutral-500 text-sm">
          {session.tier_label}
          {date && ` · ${date}`}
        </span>
      </div>

      <div className="flex items-center justify-between mt-auto pt-3 border-t border-neutral-100">
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
      className="flex flex-col gap-6 w-full max-w-6xl mx-auto pt-8 pb-16 px-4 sm:px-8 lg:px-12"
    >
      <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight">Reports</h2>
      <SummaryBlock sessions={sessions} />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {sessions.map((session) => (
          <SessionCard key={session.session_id} session={session} />
        ))}
      </div>
    </div>
  );
}
