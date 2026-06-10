'use client';

import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileCode2,
  Globe2,
  RefreshCcw,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { api } from '../../lib/api';
import type { PageAuditCheck, PageAuditReport } from '../../lib/api/types';
import { DataRegionLoading, InlineAlert, PageHeader, SectionHeader, TabBar } from '../ui/patterns';
import { Badge, Button, Card } from '../ui/primitives';

type CheckGroup = 'source' | 'dom' | 'diff';

const SCORE_META: Array<{
  key: keyof PageAuditReport['scores'];
  label: string;
}> = [
  { key: 'seo', label: 'SEO' },
  { key: 'performance_indicators', label: 'Performance' },
  { key: 'structured_data', label: 'Structured Data' },
  { key: 'accessibility', label: 'Accessibility' },
  { key: 'ecommerce_readiness', label: 'Ecommerce' },
];

export function PageAuditWorkspace({ jobId }: Readonly<{ jobId: number }>) {
  const router = useRouter();
  const [activeGroup, setActiveGroup] = useState<CheckGroup>('source');

  const detailQuery = useQuery({
    queryKey: ['page-audit-job', jobId],
    queryFn: () => api.getPageAuditJob(jobId),
    refetchInterval: (query) => {
      const status = String(query.state.data?.job.status ?? '');
      return status === 'queued' || status === 'running' ? 2000 : false;
    },
  });
  const job = detailQuery.data?.job ?? null;
  const report = detailQuery.data?.result?.report_json ?? null;
  const running = job?.status === 'queued' || job?.status === 'running';
  const checks = useMemo(() => checksForGroup(report, activeGroup), [activeGroup, report]);

  const actions = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <Button
        type="button"
        variant="neutral"
        size="sm"
        onClick={() => router.replace('/crawl?tool=audit')}
      >
        <ClipboardCheck className="size-3" />
        New Audit
      </Button>
      <Button
        type="button"
        variant="neutral"
        size="sm"
        onClick={() => void detailQuery.refetch()}
        disabled={detailQuery.isFetching}
      >
        <RefreshCcw className="size-3" />
        Refresh
      </Button>
      {report ? (
        <>
          <Button asChild variant="neutral" size="sm">
            <a href={api.exportPageAuditJson(jobId)} download>
              <Download className="size-3" />
              Export JSON
            </a>
          </Button>
          <Button asChild variant="download" size="sm">
            <a href={api.exportPageAuditMarkdown(jobId)} download>
              <Download className="size-3" />
              Export Markdown
            </a>
          </Button>
        </>
      ) : null}
    </div>
  );

  return (
    <div className="page-stack gap-5">
      <PageHeader
        title="Crawl Studio"
        description="Page technical audit results."
        actions={actions}
      />
      {detailQuery.error ? (
        <InlineAlert
          tone="danger"
          message={
            detailQuery.error instanceof Error
              ? detailQuery.error.message
              : 'Unable to load page audit.'
          }
        />
      ) : null}
      {job?.status === 'failed' ? (
        <InlineAlert tone="danger" message={String(job.summary.error || 'Page audit failed.')} />
      ) : null}

      {detailQuery.isLoading || running ? <DataRegionLoading count={5} /> : null}

      {report ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {SCORE_META.map(({ key, label }) => (
              <Card key={key} className="space-y-2 p-4">
                <div className="text-muted type-label">{label}</div>
                <div className="type-heading-1 tabular-nums">
                  {report.scores[key] == null ? 'N/A' : Math.round(report.scores[key] ?? 0)}
                </div>
              </Card>
            ))}
          </section>

          <section className="space-y-3">
            <SectionHeader
              title="Critical Failures"
              icon={AlertTriangle}
              description={`${report.critical_failures.length} blocking issue${report.critical_failures.length === 1 ? '' : 's'}`}
            />
            {report.critical_failures.length ? (
              <div className="grid gap-2">
                {report.critical_failures.map((check) => (
                  <FailureRow key={check.id} check={check} />
                ))}
              </div>
            ) : (
              <div className="border-border bg-panel flex items-center gap-2 rounded-md border px-4 py-3">
                <CheckCircle2 className="text-success size-4" />
                <span className="type-body">No critical failures.</span>
              </div>
            )}
          </section>

          <section className="space-y-3">
            <TabBar
              value={activeGroup}
              onChange={(value) => setActiveGroup(value as CheckGroup)}
              options={[
                { value: 'source', label: 'Source', icon: <FileCode2 className="size-3.5" /> },
                { value: 'dom', label: 'Rendered DOM', icon: <Globe2 className="size-3.5" /> },
                { value: 'diff', label: 'Source vs DOM' },
              ]}
            />
            <div className="border-border overflow-hidden rounded-md border">
              <table className="w-full table-fixed border-collapse text-left">
                <thead className="bg-background-alt">
                  <tr>
                    <th className="w-24 px-3 py-2 text-xs font-semibold">Status</th>
                    <th className="px-3 py-2 text-xs font-semibold">Check</th>
                    <th className="hidden w-[34%] px-3 py-2 text-xs font-semibold lg:table-cell">
                      Detected
                    </th>
                    <th className="hidden w-[28%] px-3 py-2 text-xs font-semibold md:table-cell">
                      Fix
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {checks.map((check) => (
                    <CheckRow key={check.id} check={check} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function FailureRow({ check }: Readonly<{ check: PageAuditCheck }>) {
  return (
    <div className="border-danger/30 bg-danger-bg grid gap-2 rounded-md border px-4 py-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,0.7fr)]">
      <div>
        <div className="type-body font-semibold">{check.label}</div>
        <div className="text-muted type-caption">{formatValue(check.detected_value)}</div>
      </div>
      <div className="type-body-sm">{check.fix}</div>
    </div>
  );
}

function CheckRow({ check }: Readonly<{ check: PageAuditCheck }>) {
  const tone = !check.applicable ? 'neutral' : check.passed ? 'success' : 'danger';
  const label = !check.applicable ? 'N/A' : check.passed ? 'Pass' : 'Fail';
  return (
    <tr className="border-border border-t align-top">
      <td className="px-3 py-3">
        <Badge tone={tone}>{label}</Badge>
      </td>
      <td className="px-3 py-3">
        <div className="type-body font-medium">{check.label}</div>
        <div className="text-muted type-caption mt-1">{check.severity}</div>
      </td>
      <td className="text-secondary type-caption hidden px-3 py-3 break-words lg:table-cell">
        {formatValue(check.detected_value)}
      </td>
      <td className="text-secondary type-caption hidden px-3 py-3 md:table-cell">
        {check.passed || !check.applicable ? '' : check.fix}
      </td>
    </tr>
  );
}

function checksForGroup(report: PageAuditReport | null, group: CheckGroup): PageAuditCheck[] {
  if (!report) return [];
  if (group === 'dom') return report.dom_checks;
  if (group === 'diff') return report.diff_checks;
  return report.source_checks;
}

function formatValue(value: unknown): string {
  if (value == null || value === '') return 'None';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
