'use client';

// Next.js App Router entrypoint for `/dashboard`; invoked by file-system routing.
import { useQuery } from '@tanstack/react-query';
import type { Route } from 'next';
import Link from 'next/link';
import { useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  Globe,
  Hash,
  LayoutDashboard,
  RefreshCw,
} from 'lucide-react';
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
import type { CrawlRun } from '../../lib/api/types';
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
    <div className="border-divider flex items-center gap-3 border-b py-2 last:border-b-0">
      <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium" title={domain}>
        {domain}
      </span>
      <div className="bg-background-alt h-2 w-28 overflow-hidden rounded-full">
        <div
          className="bg-accent h-full rounded-full transition-[width] duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-muted w-8 text-right font-mono text-sm tabular-nums">{count}</span>
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
      href={`/crawl?run_id=${run.id}` as Route}
      className="group hover:bg-background-alt flex items-center gap-3 rounded-lg p-2 no-underline transition-colors"
    >
      <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
      <span className="type-body text-foreground group-hover:text-accent min-w-0 flex-1 truncate font-medium transition-colors">
        {domain || `Run #${run.id}`}
      </span>
      <span className="type-body-sm text-secondary w-24 text-right whitespace-nowrap tabular-nums">
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
        <ArrowUpRight className="text-muted size-3 shrink-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100" />
      </div>
    </Link>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['dashboard'],
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

  /* Derived stats */
  const totalDomains = data?.top_domains?.length ?? 0;
  const maxDomainCount = data?.top_domains?.[0]?.count ?? 1;

  /* Status distribution */
  const statusCounts = (data?.recent_runs ?? []).reduce<Record<string, number>>((acc, run) => {
    acc[run.status] = (acc[run.status] ?? 0) + 1;
    return acc;
  }, {});
  const totalInDistribution = Object.values(statusCounts).reduce((a, b) => a + b, 0);
  const sortedStatusEntries = Object.entries(statusCounts).sort(([, a], [, b]) => b - a);

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

      {/* ── Metric Pulse (Unified) ── */}
      {isLoading ? (
        <MetricPulse>
          <MetricPulseSkeleton />
          <MetricPulseSkeleton />
          <MetricPulseSkeleton />
          <MetricPulseSkeleton />
        </MetricPulse>
      ) : (
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
            value={totalDomains.toLocaleString()}
            icon={Globe}
          />
        </MetricPulse>
      )}

      {/* ── Lower grid ── */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
        {/* Recent runs */}
        <SurfaceSection
          title="Recent Runs"
          description="Last 10 jobs"
          action={
            <Link href="/runs" className="link-accent type-control no-underline hover:underline">
              View all
            </Link>
          }
          bodyClassName="p-4 space-y-2"
        >
          {isLoading ? (
            <SkeletonRows count={6} className="p-4" />
          ) : data?.recent_runs?.length ? (
            data.recent_runs.slice(0, 10).map((run) => <RunActivityRow key={run.id} run={run} />)
          ) : (
            <div className="py-4">
              <EmptyPanel title="No runs yet" description="Submit a crawl to see activity here." />
            </div>
          )}
        </SurfaceSection>
        {/* Top domains */}
        <SurfaceSection
          title="Top Domains"
          description="By run count"
          bodyClassName="p-4 space-y-3"
        >
          {isLoading ? (
            <SkeletonRows count={5} />
          ) : data?.top_domains?.length ? (
            <div className="divide-border/50 divide-y">
              {data.top_domains.map((item) => (
                <DomainBar
                  key={item.domain}
                  domain={item.domain}
                  count={item.count}
                  max={maxDomainCount}
                />
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
      </div>

      <SurfaceSection title="Run Status" description="Recent run distribution" bodyClassName="p-4">
        {!isLoading && totalInDistribution > 0 ? (
          <div className="space-y-4">
            <div className="bg-background-alt flex h-3 w-full gap-px overflow-hidden rounded-full">
              {sortedStatusEntries.map(([status, count]) => (
                <StatusSegment
                  key={status}
                  status={status}
                  count={count}
                  total={totalInDistribution}
                />
              ))}
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {sortedStatusEntries.map(([status, count]) => (
                <div
                  key={status}
                  className="border-border bg-background-alt flex items-center justify-between rounded-lg border px-3 py-2"
                >
                  <Badge tone={statusTone(status)} flat={isSubduedStatus(status)}>
                    {statusLabel(status)}
                  </Badge>
                  <span className="text-primary font-mono text-sm tabular-nums">{count}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <DataRegionEmpty
            title="No status data yet"
            description="Run crawls to build status distribution."
            className="px-0 py-0"
          />
        )}
      </SurfaceSection>
    </div>
  );
}
