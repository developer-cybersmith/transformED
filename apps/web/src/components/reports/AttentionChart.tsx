'use client';

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { useMediaQuery } from '@/hooks/use-media-query';

interface TimelinePoint {
  minute: number;
  ces: number;
}

interface InterventionEvent {
  minute: number;
  type: string;
}

interface AttentionChartProps {
  timeline: TimelinePoint[] | null;
  interventions: InterventionEvent[] | null;
}

// Reuses the EXACT thresholds already established by cesScoreColor/formatCesLabel
// (apps/web/src/lib/utils.ts) so this chart and the Focus tile above it never
// disagree about what "Low"/"Medium"/"High" mean. Never shows a raw CES number --
// this is the only formatter the Y-axis ever calls.
function bandLabel(ces: number): 'Low' | 'Medium' | 'High' {
  if (ces >= 70) return 'High';
  if (ces >= 50) return 'Medium';
  return 'Low';
}

const BAND_TICKS = [15, 60, 85]; // representative points inside Low/Medium/High

const INTERVENTION_COLORS: Record<string, string> = {
  distraction: '#e11d48', // rose-600
  fatigue: '#d97706', // amber-600
  confusion: '#7c3aed', // violet-600
};

function interventionColor(type: string): string {
  return INTERVENTION_COLORS[type] ?? '#71717a'; // neutral-500 fallback for unknown types
}

/**
 * S3-05 (Story 2-46). Area chart of CES over session time for the session report.
 *
 * D77 (docs/DEFECT-REGISTER.md): `timeline` can only ever hold the last
 * _CES_HISTORY_MAX=10 windows -- the last ~50s of the session at default cadence,
 * regardless of how long the session actually ran. This component always labels
 * that honestly as a recency window (AC-6) and never implies full-session coverage.
 *
 * Never renders a raw CES number anywhere -- the Y-axis shows only qualitative
 * Low/Medium/High bands (bandLabel(), matching utils.ts's thresholds exactly).
 */
export function AttentionChart({ timeline, interventions }: AttentionChartProps) {
  const isMobile = useMediaQuery('(max-width: 639px)');

  if (!timeline || timeline.length < 2) {
    return (
      <div
        data-testid="attention-chart-empty"
        className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm"
      >
        <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
          Attention Over Time
        </span>
        <span className="text-neutral-500 text-sm">Not enough data for a timeline yet</span>
      </div>
    );
  }

  return (
    <div
      data-testid="attention-chart"
      className="flex flex-col gap-1.5 p-5 rounded-2xl bg-white border border-neutral-100 shadow-sm"
    >
      <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
        Attention Over Time
      </span>
      <div data-testid="attention-chart-recency-caption" className="text-neutral-400 text-xs">
        Showing the most recent {timeline.length} reading{timeline.length === 1 ? '' : 's'} of
        this session
      </div>
      <ResponsiveContainer width="100%" height={isMobile ? 140 : 220}>
        <AreaChart data={timeline} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="minute"
            hide={isMobile}
            tickFormatter={(minute: number) => `${minute}m`}
            fontSize={12}
            stroke="#a1a1aa"
          />
          <YAxis
            type="number"
            domain={[0, 100]}
            ticks={BAND_TICKS}
            tickFormatter={(value: number) => bandLabel(value)}
            fontSize={12}
            stroke="#a1a1aa"
            width={52}
          />
          <Area
            type="monotone"
            dataKey="ces"
            stroke="#059669"
            fill="#059669"
            fillOpacity={0.15}
            isAnimationActive={false}
          />
          {(interventions ?? []).map((event, i) => (
            <ReferenceLine
              key={`${event.type}-${event.minute}-${i}`}
              x={event.minute}
              stroke={interventionColor(event.type)}
              strokeDasharray="4 2"
              label={(props: { viewBox?: { x?: number; y?: number } }) => (
                <g
                  data-testid={`intervention-marker-${event.type}`}
                  transform={`translate(${props.viewBox?.x ?? 0}, ${props.viewBox?.y ?? 0})`}
                >
                  <title>
                    {event.type} at minute {event.minute}
                  </title>
                </g>
              )}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
