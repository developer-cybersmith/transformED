'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, Clock3, Inbox, AlertCircle, SearchX } from 'lucide-react';
import { useSessionReports } from '@/hooks/useSessionReports';
import { cesScoreColor, formatCesLabel } from '@/lib/utils';
import type { SessionSummary } from '@/types/assessment';

// Story 2-58 (BR-7): Sidebar.tsx's "Reports" nav link has pointed at /reports
// since it was first built, with no route behind it -- 404 from the
// beginning. This page (and GET /assessment/sessions behind it) is the fix.
// Story 2-59 (BR-8): widened from a single narrow column into a full-width,
// block-divided layout (summary row + card grid) per direct user feedback.
// Follow-up (same story, same-day feedback): a flat wall of every session at
// once "looks too exhausted" for anyone with more than a handful -- added
// filter tabs, recency grouping, and a "Load more" reveal so the page reads
// as organized, not overwhelming.
// Standalone page, no dashboard shell -- matches the existing convention for
// /reports/[sessionId] (SessionReport.tsx), which is also sidebar-less.

const BLOCK_CLASS = 'rounded-2xl bg-white border border-neutral-100 shadow-sm';
const INITIAL_VISIBLE = 9;
const LOAD_MORE_STEP = 9;
const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

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

// `now` is a parameter (not a bare `Date.now()` call inside) so tests can pin
// it via a fixed reference instead of depending on real wall-clock time.
function isWithinLastWeek(isoString: string | null, now: number): boolean {
  if (!isoString) return false;
  const t = new Date(isoString).getTime();
  if (Number.isNaN(t)) return false;
  return t <= now && now - t < ONE_WEEK_MS;
}

type FilterKey = 'all' | 'completed' | 'in-progress';

function matchesFilter(session: SessionSummary, filter: FilterKey): boolean {
  if (filter === 'completed') return session.completed;
  if (filter === 'in-progress') return !session.completed;
  return true;
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
// client-side from the already-fetched list, no new network call. Always
// reflects the FULL list regardless of the active filter tab below it (a
// global overview, not a filtered one).
function SummaryBlock({ sessions }: { sessions: SessionSummary[] }) {
  const completedCount = sessions.filter((s) => s.completed).length;
  const inProgressCount = sessions.length - completedCount;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
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

function FilterTabs({
  sessions,
  active,
  onChange,
}: {
  sessions: SessionSummary[];
  active: FilterKey;
  onChange: (filter: FilterKey) => void;
}) {
  const tabs: { key: FilterKey; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: sessions.length },
    { key: 'completed', label: 'Completed', count: sessions.filter((s) => s.completed).length },
    { key: 'in-progress', label: 'In Progress', count: sessions.filter((s) => !s.completed).length },
  ];

  return (
    <div role="tablist" className="flex items-center gap-2 flex-wrap">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={active === tab.key}
          onClick={() => onChange(tab.key)}
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${
            active === tab.key
              ? 'bg-[var(--accent-secondary)] text-primary'
              : 'bg-white border border-neutral-200 text-neutral-600 hover:border-neutral-300'
          }`}
        >
          {tab.label} ({tab.count})
        </button>
      ))}
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

function SessionGroup({ label, sessions }: { label: string; sessions: SessionSummary[] }) {
  if (sessions.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">{label}</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {sessions.map((session) => (
          <SessionCard key={session.session_id} session={session} />
        ))}
      </div>
    </div>
  );
}

export function ReportsIndex() {
  const { sessions, isLoading, error } = useSessionReports();
  const [activeFilter, setActiveFilter] = useState<FilterKey>('all');
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  // A snapshot taken once at mount, not read fresh on every render -- `Date.now()`
  // is an impure call React's rules forbid during render (react-hooks/purity).
  // "This Week" grouping doesn't need to be reactive to the wall clock ticking
  // while the page is open.
  const [now] = useState(() => Date.now());

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState />;
  if (sessions.length === 0) return <EmptyState />;

  const filtered = sessions.filter((s) => matchesFilter(s, activeFilter));
  const visible = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > visible.length;
  const thisWeek = visible.filter((s) => isWithinLastWeek(s.started_at, now));
  const earlier = visible.filter((s) => !isWithinLastWeek(s.started_at, now));

  function handleFilterChange(filter: FilterKey) {
    setActiveFilter(filter);
    setVisibleCount(INITIAL_VISIBLE);
  }

  return (
    <div
      data-testid="reports-index-root"
      className="flex flex-col gap-6 w-full max-w-6xl mx-auto pt-8 pb-16 px-4 sm:px-8 lg:px-12"
    >
      <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight">Reports</h2>
      <SummaryBlock sessions={sessions} />
      <FilterTabs sessions={sessions} active={activeFilter} onChange={handleFilterChange} />

      {filtered.length === 0 ? (
        <div
          data-testid="reports-index-no-match"
          className="flex flex-col items-center justify-center py-16 text-center gap-3"
        >
          <SearchX className="w-8 h-8 text-neutral-300" />
          <p className="text-neutral-500">No sessions match this filter.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <SessionGroup label="This Week" sessions={thisWeek} />
          <SessionGroup label="Earlier" sessions={earlier} />
        </div>
      )}

      {hasMore && (
        <button
          type="button"
          onClick={() => setVisibleCount((c) => c + LOAD_MORE_STEP)}
          className="self-center px-6 py-2.5 rounded-full bg-white border border-neutral-200 text-neutral-700 text-sm font-semibold hover:border-neutral-300 transition-all"
        >
          Load more
        </button>
      )}
    </div>
  );
}
