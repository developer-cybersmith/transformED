import { SessionReport } from '@/components/reports/SessionReport';

interface SessionReportPageProps {
  params: Promise<{ sessionId: string }>;
}

export default async function SessionReportPage({ params }: SessionReportPageProps) {
  const { sessionId } = await params;
  return <SessionReport sessionId={sessionId} />;
}
