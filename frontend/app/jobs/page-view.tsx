import { useQuery } from '@tanstack/react-query';
import { RefreshCw, XCircle } from 'lucide-react';
import { useState } from 'react';

import { queryKeys } from '@/api/query-keys';

import { crawlsApi } from '../../lib/api/crawls';
import { jobsApi } from '../../lib/api/jobs';
import type { ActiveJob } from '../../lib/api/types';
import { formatJobsTimestamp as formatTimestamp, formatTimeHms } from '../../lib/format/date';
import { humanizeStatus, jobsStatusTone as statusTone } from '../../lib/ui/status';
import { ActionButton } from '../../components/ui/action-button';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  ProgressBar,
  SectionCard,
} from '../../components/ui/patterns';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { Badge, Button } from '../../components/ui/primitives';

// Suppress JS-0067: this page owns cohesive job-state UX.
// Polling, actions, and table rendering share local state here.
// skipcq: JS-0067
export default function JobsPage() {
  const [pendingAction, setPendingAction] = useState('');
  const [actionError, setActionError] = useState('');
  const {
    data: jobsData,
    dataUpdatedAt: jobsDataUpdatedAt,
    isLoading: isJobsLoading,
    isError: isJobsError,
    refetch: refetchJobs,
  } = useQuery({
    queryKey: queryKeys.jobs.active(),
    queryFn: jobsApi.listJobs,
    refetchInterval: 5000,
  });

  const jobs = jobsData ?? [];

  const lastRefreshed = jobsDataUpdatedAt
    ? formatTimeHms(new Date(jobsDataUpdatedAt).toISOString())
    : '--';

  async function runAction(runId: number) {
    const action = 'kill';
    setPendingAction(`${action}:${runId}`);
    try {
      setActionError('');
      await crawlsApi.killCrawl(runId);
      await refetchJobs();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : `Unable to ${action} run ${runId}.`);
    } finally {
      setPendingAction('');
    }
  }

  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Jobs"
        description="Live run state for the local dev runner."
        actions={
          <div className="flex items-center gap-3">
            <span className="type-caption">Last refreshed {lastRefreshed}</span>
            <Button variant="neutral" type="button" size="sm" onClick={() => void refetchJobs()}>
              <RefreshCw className="size-3.5" />
              Refresh
            </Button>
          </div>
        }
      />

      <SectionCard
        title="Active Jobs"
        description="Auto-refreshes every 5 seconds. Hard kill is the only active-run control in dev mode."
        action={<Badge tone="neutral">{jobs.length} active</Badge>}
      >
        {actionError ? <InlineAlert message={actionError} /> : null}

        {isJobsLoading ? (
          <DataRegionLoading count={6} />
        ) : isJobsError ? (
          <DataRegionError message="Failed to load jobs." />
        ) : jobs.length ? (
          <>
            <Table
              // 260px accounts for page header, navigation, filters, and padding.
              wrapperClassName="max-h-[max(200px,calc(100vh-260px))] rounded-md border border-border"
              className="compact-data-table min-w-[960px] table-fixed"
            >
              <colgroup>
                <col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} />
                <col style={{ width: '30%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} />
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead>Run ID</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Target URL</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="pr-4 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow key={job.run_id}>
                    <TableCell className="font-mono text-base">{job.run_id}</TableCell>
                    <TableCell className="text-base">{formatJobType(job.type)}</TableCell>
                    <TableCell
                      className="max-w-[320px] truncate font-mono text-base"
                      title={job.url}
                    >
                      {job.url}
                    </TableCell>
                    <TableCell>
                      <ProgressBar percent={job.progress} />
                    </TableCell>
                    <TableCell className="text-base text-secondary">
                      {formatTimestamp(job.started_at)}
                    </TableCell>
                    <TableCell style={{ overflow: 'visible', textOverflow: 'clip' }}>
                      <StatusPill status={job.status} />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <ActionButton
                          icon={XCircle}
                          label="Hard Kill"
                          disabled={
                            !(
                              job.status === 'pending' ||
                              job.status === 'running' ||
                              job.status === 'paused'
                            ) || Boolean(pendingAction)
                          }
                          onClick={() => void runAction(job.run_id)}
                          danger
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="table-footer-rail flex items-center justify-between px-4 py-2">
              <span>Showing {jobs.length} active jobs</span>
              <span>Last refresh {lastRefreshed}</span>
            </div>
          </>
        ) : (
          <DataRegionEmpty
            title="No active jobs"
            description="Start a crawl to see live workers here."
          />
        )}
      </SectionCard>
    </div>
  );
}

function StatusPill({ status }: Readonly<{ status: ActiveJob['status'] }>) {
  const tone = statusTone(status);
  return (
    <Badge tone={tone} flat={status === 'killed'}>
      {humanizeStatus(status)}
    </Badge>
  );
}

function formatJobType(value: string) {
  switch (value) {
    case 'crawl':
      return 'Single';
    case 'batch':
      return 'Batch';
    case 'csv':
      return 'CSV';
    default:
      return value;
  }
}
