'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import type { ComponentType } from 'react';
import { ArrowLeft, Target, MessageCircle, Gauge, Clock3, Dna as DnaIcon, RotateCcw } from 'lucide-react';
import { useSessionReport } from '@/hooks/useSessionReport';
import { cesScoreColor, formatCesLabel, formatTeachbackLabel } from '@/lib/utils';
import type { DnaDimension, LearnerDnaSnapshot, TeachbackDetail } from '@/types/assessment';

// Story 2-56 (S4-05): recharts ships as its own ~390KB chunk (confirmed via
// a real `next build` — apps/web/.next's client-reference-manifest listed it
// in this route's entryJSFiles unconditionally). Static import meant every
// /reports/[sessionId] visit paid that cost even when `ces_timeline` is null
// and the chart never renders below. next/dynamic defers the import to the
// point AttentionChart actually mounts -- mirrors PlayerLoader.tsx's own
// `dynamic(() => import('./Player'), { ssr: false, ... })`, the one other
// place this repo already does this. ssr: false because ResponsiveContainer
// (recharts) measures a real DOM node -- nothing useful to render server-side
// anyway, same reasoning PlayerLoader's comment gives for Player.
const AttentionChart = dynamic(
  () => import('@/components/reports/AttentionChart').then((mod) => mod.AttentionChart),
  {
    ssr: false,
    loading: () => (
      <div
        data-testid="attention-chart-skeleton"
        className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm"
      >
        <div className="h-3 w-32 rounded bg-neutral-100 animate-pulse" />
        <div className="h-[220px] rounded-xl bg-neutral-100 animate-pulse mt-1.5" />
      </div>
    ),
  }
);

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

// Story 2-59 (BR-8): shared block chrome for every card on this page — one
// visual language, not a per-section reinvention.
const BLOCK_CLASS = 'rounded-2xl bg-white border border-neutral-100 shadow-sm';

function DnaSnapshotSection({ snapshot }: { snapshot: LearnerDnaSnapshot }) {
  return (
    <div data-testid="dna-snapshot-section" className={`flex flex-col gap-3 p-5 ${BLOCK_CLASS}`}>
      <span className="flex items-center gap-2 text-xs font-medium text-neutral-500 uppercase tracking-wider">
        <DnaIcon className="w-3.5 h-3.5" />
        Learner DNA Snapshot
      </span>
      <div className="grid grid-cols-1 gap-x-6 gap-y-2">
        {DIMENSION_ORDER.map((dim) => {
          const growth = snapshot.growth_labels[dim];
          return (
            <div key={dim} className="flex items-center justify-between gap-2">
              <span className="text-neutral-700 text-sm">{DIMENSION_DISPLAY_NAMES[dim]}</span>
              <span className="text-neutral-900 text-sm font-medium flex items-center gap-1.5">
                {snapshot.dimension_labels[dim]}
                {growth !== null && (
                  <span data-testid={`dna-growth-${dim}`} aria-label={growth} title={growth}>
                    {GROWTH_INDICATORS[growth] ?? '•'}
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

// Story 2-48 (S3-06) — per-segment teach-back detail. `entry.score` is bucketed through
// `formatTeachbackLabel` (same helper the aggregate Teach-Back tile uses) and never printed
// raw -- PRD: no rubric score shown to students in Phase 1. `segment_id` is an internal
// identifier, never shown -- the array's index (already chronological, per the backend's
// `.order("created_at")`) is used for the display label instead.
function TeachbackDetailSection({ details }: { details: TeachbackDetail[] }) {
  return (
    <div data-testid="teachback-detail-section" className={`flex flex-col gap-4 p-5 ${BLOCK_CLASS}`}>
      <span className="flex items-center gap-2 text-xs font-medium text-neutral-500 uppercase tracking-wider">
        <MessageCircle className="w-3.5 h-3.5" />
        Teach-Back Detail
      </span>
      {details.map((entry, index) => (
        <div
          key={`${entry.segment_id}-${entry.attempt_number}`}
          data-testid={`teachback-detail-item-${index}`}
          className="flex flex-col gap-1.5 border-t border-neutral-100 pt-4 first:border-t-0 first:pt-0"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-neutral-900 text-sm font-medium">Segment {index + 1}</span>
            <span className="text-neutral-500 text-sm">{formatTeachbackLabel(entry.score)}</span>
          </div>
          {entry.feedback_praise && (
            <p className="text-neutral-700 text-sm">{entry.feedback_praise}</p>
          )}
          {entry.feedback_correction && (
            <p className="text-neutral-700 text-sm">{entry.feedback_correction}</p>
          )}
          {entry.concepts_hit.length > 0 && (
            <div
              data-testid={`teachback-concepts-hit-${index}`}
              className="flex flex-wrap items-center gap-1.5"
            >
              <span className="text-neutral-400 text-xs uppercase tracking-wide">Hit</span>
              {entry.concepts_hit.map((concept) => (
                <span
                  key={concept}
                  className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-xs"
                >
                  {concept}
                </span>
              ))}
            </div>
          )}
          {entry.concepts_missed.length > 0 && (
            <div
              data-testid={`teachback-concepts-missed-${index}`}
              className="flex flex-wrap items-center gap-1.5"
            >
              <span className="text-neutral-400 text-xs uppercase tracking-wide">Missed</span>
              {entry.concepts_missed.map((concept) => (
                <span
                  key={concept}
                  className="px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 text-xs"
                >
                  {concept}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function LoadingState() {
  return (
    <div
      data-testid="session-report-loading"
      className="flex flex-col gap-6 w-full max-w-6xl mx-auto pt-8 pb-16 px-4 sm:px-8 lg:px-12 animate-pulse"
    >
      <div className="h-28 rounded-3xl bg-neutral-100" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
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
      className="flex flex-col items-center justify-center max-w-2xl mx-auto pt-24 pb-24 px-4 sm:px-8 lg:px-12 text-center gap-6"
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

// D161: pinned to 'en-US' explicitly -- see ReportsIndex.tsx's formatSessionDate
// for the full hydration-mismatch rationale (SSR/browser locale disagreement).
function formatCompletedAt(isoString: string): string | null {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
}

// Story 2-59 (BR-8): one stat tile, shared by the 4-across stats block.
function StatTile({
  icon: Icon,
  label,
  value,
  valueClassName,
  detail,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string;
  valueClassName?: string;
  detail?: string;
}) {
  return (
    <div className={`flex flex-col gap-2 p-5 ${BLOCK_CLASS}`}>
      <span className="flex items-center gap-2 text-xs font-medium text-neutral-500 uppercase tracking-wider">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </span>
      <span className={`font-medium text-lg ${valueClassName ?? 'text-neutral-900'}`}>{value}</span>
      {detail && <span className="text-neutral-500 text-sm">{detail}</span>}
    </div>
  );
}

export function SessionReport({ sessionId }: SessionReportProps) {
  const { report, isLoading, error } = useSessionReport(sessionId);

  if (isLoading) return <LoadingState />;
  if (error || !report) return <ErrorState />;

  const completedAt = report.completed_at ? formatCompletedAt(report.completed_at) : null;
  const hasChart = report.ces_timeline !== null;
  const hasTeachbackDetail = !!report.teachback_details && report.teachback_details.length > 0;
  const hasDna = !!report.learner_dna_snapshot;

  return (
    <div
      data-testid="session-report-root"
      className="flex flex-col gap-6 w-full max-w-6xl mx-auto pt-8 pb-16 px-4 sm:px-8 lg:px-12"
    >
      <Link
        href="/reports"
        className="inline-flex items-center gap-1.5 self-start text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Reports
      </Link>

      {/* Header block */}
      <div className={`flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6 ${BLOCK_CLASS}`}>
        <div>
          <h2 className="font-serif text-2xl sm:text-3xl font-semibold text-neutral-900 tracking-tight">
            Session Report
          </h2>
          <p className="text-neutral-500 mt-1">
            {report.tier_label} Session{completedAt && ` · ${completedAt}`}
          </p>
        </div>
        <div className="flex items-center gap-3 px-5 py-3 rounded-2xl bg-neutral-50 border border-neutral-100 self-start sm:self-auto">
          <Gauge className={`w-6 h-6 ${cesScoreColor(report.ces_score)}`} />
          <div className="flex flex-col">
            <span className="text-xs text-neutral-400 uppercase tracking-wide">Focus</span>
            <span className={`text-sm font-semibold ${cesScoreColor(report.ces_score)}`}>
              {formatCesLabel(report.ces_score)}
              {report.ces_score !== null && ` · ${Math.round(report.ces_score)}/100`}
            </span>
          </div>
        </div>
      </div>

      {/* Stats block */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile
          icon={Target}
          label="Quiz Accuracy"
          value={
            report.quiz_accuracy_label === null
              ? 'No quiz questions this session'
              : `${report.quiz_correct_count} / ${report.quiz_total_questions} correct`
          }
          detail={report.quiz_accuracy_label ?? undefined}
        />
        <StatTile
          icon={MessageCircle}
          label="Teach-Back"
          value={formatTeachbackLabel(report.teachback_score)}
        />
        <StatTile
          icon={Gauge}
          label="Focus"
          value={formatCesLabel(report.ces_score)}
          valueClassName={cesScoreColor(report.ces_score)}
          detail={report.ces_score !== null ? `${Math.round(report.ces_score)}/100` : undefined}
        />
        <StatTile
          icon={Clock3}
          label="Engagement"
          value={formatDuration(report.duration_minutes)}
          detail={formatInterventions(report.interventions_count)}
        />
      </div>

      {/* Chart, full width when present -- gets its own row rather than being
          squeezed into a 2/3 column, since it's the primary visual insight. */}
      {hasChart && (
        <AttentionChart timeline={report.ces_timeline} interventions={report.intervention_events} />
      )}

      {/* Teach-Back Detail and Learner DNA Snapshot, paired side-by-side when
          both exist (both are list-shaped content of comparable density, so
          this pairing rarely produces the lopsided-height gap a chart-vs-DNA
          pairing did) -- either one alone takes the full row instead of being
          stranded in a half-empty column. Document order (teach-back detail
          before DNA snapshot) still holds regardless, since it's literally
          first in this markup either way. */}
      {(hasTeachbackDetail || hasDna) && (
        <div
          className={
            hasTeachbackDetail && hasDna
              ? 'grid grid-cols-1 lg:grid-cols-2 gap-6 items-start'
              : 'grid grid-cols-1 gap-6'
          }
        >
          {hasTeachbackDetail && <TeachbackDetailSection details={report.teachback_details!} />}
          {hasDna && <DnaSnapshotSection snapshot={report.learner_dna_snapshot!} />}
        </div>
      )}

      {/* Closing action, always full-width -- never competes for height
          against DNA/chart/teach-back content above it. */}
      <div className={`flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6 ${BLOCK_CLASS}`}>
        <p className="text-neutral-600 text-sm">
          Revisit this lesson any time to reinforce what you&apos;ve learned.
        </p>
        <Link
          href={`/lesson/${report.lesson_id}`}
          className="self-start sm:self-auto inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-full bg-[var(--accent-secondary)] text-primary text-sm font-semibold hover:brightness-105 transition-all"
        >
          <RotateCcw className="w-4 h-4" />
          Study Again
        </Link>
      </div>
    </div>
  );
}
