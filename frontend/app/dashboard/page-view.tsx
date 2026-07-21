import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useState } from 'react';
import { Activity, ArrowUpRight, Globe, Hash, LayoutDashboard, RefreshCw } from 'lucide-react';
import { queryKeys } from '@/api/query-keys';
import { Badge, Button } from '../../components/ui/primitives';
import {
  DataRegionEmpty,
  EmptyPanel,
  MetricPulse,
  MetricPulseItem,
  MetricPulseSkeleton,
  PageHeader,
  SkeletonRows,
  StatusDot,
  SurfaceSection,
} from '../../components/ui/patterns';
import { api } from '../../lib/api';
import type { CrawlRun, Dashboard } from '../../lib/api/types';
import { getDomain } from '../../lib/format/domain';
import {
  dashboardStatusBarColor,
  dashboardStatusLabel as statusLabel,
  dashboardStatusTone as statusTone,
  isSubduedStatus,
  runExecutionLabel,
  runExecutionTone,
} from '../../lib/ui/status';

/* ─── Domain bar ─────────────────────────────────────────────────────────── */
function DomainBar({
  domain,
  count,
  max,
}: Readonly<{ domain: string; count: number; max: number }>) {
  const pct = max > 0 ? Math.round((count / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3 border-b border-divider py-2 last:border-b-0">
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground" title={domain}>
        {domain}
      </span>
      <div className="h-1 w-28 overflow-hidden rounded-full bg-background-alt">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-8 text-right font-mono text-sm text-muted tabular-nums">{count}</span>
    </div>
  );
}

/* ─── Status distribution row ────────────────────────────────────────────── */
function StatusSegment({
  status,
  count,
  total,
}: Readonly<{ status: string; count: number; total: number }>) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  if (pct < 0.5) return null;
  const color = dashboardStatusBarColor(status);
  return (
    <div
      className="h-full first:rounded-l-full last:rounded-r-full"
      style={{ width: `${pct}%`, background: color }}
      title={`${statusLabel(status)}: ${count}`}
    />
  );
}

/* ─── Run activity row ───────────────────────────────────────────────────── */
function RunActivityRow({ run }: Readonly<{ run: CrawlRun }>) {
  const domain = getDomain(run.url);
  const recordCount = run.result_summary?.record_count ?? 0;

  return (
    <Link
      to={`/crawl?run_id=${run.id}`}
      className="group flex items-center gap-3 rounded-lg p-2 no-underline transition-colors hover:bg-background-alt"
    >
      <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
        {domain || `Run #${run.id}`}
      </span>
      <span className="w-24 text-right text-sm whitespace-nowrap text-muted tabular-nums">
        {recordCount.toLocaleString()} rec
      </span>
      <div className="flex w-28 justify-start">
        <Badge
          tone={runExecutionTone(run.status, run.result_summary)}
          flat={isSubduedStatus(run.status)}
        >
          {runExecutionLabel(run.status, run.result_summary)}
        </Badge>
      </div>
      <div className="w-4">
        <ArrowUpRight className="size-3 shrink-0 text-muted opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100" />
      </div>
    </Link>
  );
}

function DashboardMetrics({ data, loading }: Readonly<{ data?: Dashboard; loading: boolean }>) {
  if (loading) {
    return (
      <MetricPulse>
        {Array.from({ length: 4 }, (_, index) => (
          <MetricPulseSkeleton key={index} />
        ))}
      </MetricPulse>
    );
  }
  return (
    <MetricPulse>
      <MetricPulseItem
        label="Total Runs"
        value={(data?.total_runs ?? 0).toLocaleString()}
        icon={Hash}
      />
      <MetricPulseItem
        label="Active Runs"
        value={(data?.active_runs ?? 0).toLocaleString()}
        icon={Activity}
        pulse={Boolean(data?.active_runs)}
      />
      <MetricPulseItem
        label="Total Records"
        value={(data?.total_records ?? 0).toLocaleString()}
        icon={LayoutDashboard}
      />
      <MetricPulseItem
        label="Unique Domains"
        value={(data?.top_domains?.length ?? 0).toLocaleString()}
        icon={Globe}
      />
    </MetricPulse>
  );
}

function RecentRuns({ runs, loading }: Readonly<{ runs?: CrawlRun[]; loading: boolean }>) {
  return (
    <SurfaceSection
      title="Recent Runs"
      description="Last 10 jobs"
      action={
        <Link to="/runs" className="link-accent type-control no-underline hover:underline">
          View all
        </Link>
      }
      bodyClassName="p-4 space-y-2"
    >
      {loading ? (
        <SkeletonRows count={6} className="p-4" />
      ) : runs?.length ? (
        runs.slice(0, 10).map((run) => <RunActivityRow key={run.id} run={run} />)
      ) : (
        <div className="py-4">
          <EmptyPanel title="No runs yet" description="Submit a crawl to see activity here." />
        </div>
      )}
    </SurfaceSection>
  );
}

function TopDomains({ data, loading }: Readonly<{ data?: Dashboard; loading: boolean }>) {
  const domains = data?.top_domains;
  const max = Math.max(1, ...(domains ?? []).map((domain) => domain.count));
  return (
    <SurfaceSection title="Top Domains" description="By run count" bodyClassName="p-4 space-y-3">
      {loading ? (
        <SkeletonRows count={5} />
      ) : domains?.length ? (
        <div className="divide-y divide-border/50">
          {domains.map((item) => (
            <DomainBar key={item.domain} domain={item.domain} count={item.count} max={max} />
          ))}
        </div>
      ) : (
        <DataRegionEmpty
          title="No domain data yet"
          description="Run crawls to build domain distribution."
          className="px-0 py-2"
        />
      )}
    </SurfaceSection>
  );
}

function RunStatusDistribution({
  runs,
  loading,
}: Readonly<{ runs?: CrawlRun[]; loading: boolean }>) {
  const statusCounts = (runs ?? []).reduce<Record<string, number>>((counts, run) => {
    counts[run.status] = (counts[run.status] ?? 0) + 1;
    return counts;
  }, {});
  const entries = Object.entries(statusCounts).sort(([, left], [, right]) => right - left);
  const total = entries.reduce((count, [, value]) => count + value, 0);
  if (loading || total === 0) {
    return (
      <DataRegionEmpty
        title="No status data yet"
        description="Run crawls to build status distribution."
        className="px-0 py-0"
      />
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex h-2.5 w-full gap-px overflow-hidden rounded-full bg-background-alt">
        {entries.map(([status, count]) => (
          <StatusSegment key={status} status={status} count={count} total={total} />
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {entries.map(([status, count]) => (
          <div
            key={status}
            className="flex items-center justify-between rounded-lg border border-border bg-background-alt px-3 py-2"
          >
            <Badge tone={statusTone(status)} flat={isSubduedStatus(status)}>
              {statusLabel(status)}
            </Badge>
            <span className="text-foreground font-mono text-sm tabular-nums">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: queryKeys.dashboard(),
    queryFn: api.dashboard,
  });
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      await refetch();
    } finally {
      setIsRefreshing(false);
    }
  }

  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Dashboard"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="neutral"
              size="sm"
              onClick={() => void handleRefresh()}
              disabled={isRefreshing || isLoading}
            >
              <RefreshCw className={`size-3.5 ${isRefreshing ? 'animate-spin-slow' : ''}`} />
              {isRefreshing ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      <DashboardMetrics data={data} loading={isLoading} />

      {/* ── Lower grid ── */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
        <RecentRuns runs={data?.recent_runs} loading={isLoading} />
        <TopDomains data={data} loading={isLoading} />
      </div>

      <SurfaceSection title="Run Status" description="Recent run distribution" bodyClassName="p-4">
        <RunStatusDistribution runs={data?.recent_runs} loading={isLoading} />
      </SurfaceSection>
    </div>
  );
}
