'use client';

import { useMemo, useState } from 'react';
import { Download, Play, RefreshCcw, Layers, CheckSquare, History, Network } from 'lucide-react';

import { InlineAlert, PageHeader, TabBar } from '../../components/ui/patterns';
import { Button, Input, Field, Toggle } from '../../components/ui/primitives';
import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';
import { api } from '../../lib/api';
import {
  UcpContractPanel,
  UcpDimensionTable,
  UcpFixSequence,
  UcpScoreSummary,
} from './ucp-audit-components';
import { useUcpAudit } from './use-ucp-audit';
import { cn } from '../../lib/utils';

export default function UcpAuditPage() {
  const controller = useUcpAudit();
  const [activeTab, setActiveTab] = useState<'compliance' | 'contract' | 'fix-sequence'>(
    'compliance',
  );
  const [historyOpen, setHistoryOpen] = useState(false);

  const description =
    controller.activeJob && controller.report
      ? `${controller.activeJob.domain} · score ${controller.report.overall_score}`
      : 'Audit product data, crawler access, and optional AI shopping-answer quality.';

  const tabOptions = useMemo(
    () => [
      { value: 'compliance', label: 'Score Breakdown', icon: <Layers className="size-3.5" /> },
      { value: 'contract', label: 'Signal Audit', icon: <Network className="size-3.5" /> },
      {
        value: 'fix-sequence',
        label: 'Repair Roadmap',
        icon: <CheckSquare className="size-3.5" />,
      },
    ],
    [],
  );

  const historyItems: HistoryItem[] = useMemo(() => {
    return controller.historyItems.map((job) => ({
      id: job.id,
      status: job.status,
      created_at: job.created_at,
      label: job.domain,
      meta:
        job.summary?.overall_score != null
          ? `${job.summary.overall_score}/100 index`
          : 'Audit run queued',
    }));
  }, [controller.historyItems]);

  return (
    <div className="page-stack gap-5">
      <PageHeader
        title="AI Discoverability Score"
        description={description}
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <Button type="button" variant="neutral" size="sm" onClick={() => setHistoryOpen(true)}>
              <History className="size-3" />
              History
            </Button>
            <Button
              type="button"
              variant="neutral"
              size="sm"
              onClick={() => void controller.detailQuery.refetch()}
              disabled={!controller.resolvedJobId || controller.detailQuery.isFetching}
            >
              <RefreshCcw
                className={cn('size-3', controller.detailQuery.isFetching && 'animate-spin')}
              />
              Refresh
            </Button>
            {controller.resolvedJobId && controller.report ? (
              <Button asChild variant="download" size="sm">
                <a href={api.exportUcpAuditMarkdown(controller.resolvedJobId)} download>
                  <Download className="size-3" />
                  Export report
                </a>
              </Button>
            ) : (
              <Button variant="download" size="sm" disabled>
                <Download className="size-3" />
                Export report
              </Button>
            )}
            <Button
              type="button"
              variant="action"
              size="sm"
              onClick={controller.startAudit}
              disabled={controller.createPending || controller.isRunning}
            >
              <Play className="size-3" />
              {controller.createPending || controller.isRunning ? 'Auditing…' : 'Start Audit'}
            </Button>
          </div>
        }
      />

      {controller.error ? (
        <div className="animate-in fade-in slide-in-from-top-1 duration-200">
          <InlineAlert tone="danger" message={controller.error} />
        </div>
      ) : null}

      {/* Horizontal Compact Config Ribbon (Saves huge space) */}
      <section className="border-border bg-panel before:bg-accent/40 relative overflow-hidden rounded-lg border p-4 shadow-sm before:absolute before:inset-y-0 before:left-0 before:w-px">
        <div className="grid gap-4 lg:grid-cols-[1fr_140px_240px] lg:items-end">
          <Field label="Target Domain" className="w-full">
            <Input
              value={controller.domain}
              onChange={(event) => controller.setDomain(event.target.value)}
              placeholder="example-domain.com"
              className="border-border focus:border-accent type-control h-[var(--control-height)]"
              aria-label="Domain"
            />
          </Field>

          <Field label="Sample Size">
            <Input
              type="number"
              min={1}
              max={50}
              value={controller.options.sample_size}
              onChange={(event) =>
                controller.setOptions((current) => ({
                  ...current,
                  sample_size: Number(event.target.value || 1),
                }))
              }
              className="type-control h-[var(--control-height)]"
            />
          </Field>

          <div className="border-border bg-background/35 flex h-[var(--control-height)] items-center justify-between gap-3 rounded-md border px-3">
            <div className="min-w-0">
              <div className="type-label text-secondary">AI reasoning</div>
              <div className="type-caption truncate">LLM review per product sample</div>
            </div>
            <Toggle
              checked={Boolean(controller.options.llm_enabled)}
              ariaLabel="Enable AI reasoning"
              onChange={(checked) =>
                controller.setOptions((current) => ({
                  ...current,
                  llm_enabled: checked,
                }))
              }
            />
          </div>
        </div>
      </section>

      {/* Full-Width Analytical Workspace Dashboard */}
      <div className="page-stack w-full gap-5">
        {/* Overall Score & Dimension metrics */}
        <UcpScoreSummary
          report={controller.report}
          job={controller.activeJob}
          loading={controller.detailQuery.isLoading || controller.isRunning}
        />

        {/* Workspace tab selectors */}
        <TabBar
          value={activeTab}
          onChange={(val) => setActiveTab(val as 'compliance' | 'contract' | 'fix-sequence')}
          options={tabOptions}
          fullWidth
          size="lg"
        />

        {/* Tab viewports spanning full width */}
        <div className="animate-in fade-in w-full min-w-0 duration-300">
          {activeTab === 'compliance' && (
            <UcpDimensionTable
              report={controller.report}
              loading={controller.detailQuery.isLoading}
            />
          )}
          {activeTab === 'contract' && <UcpContractPanel report={controller.report} />}
          {activeTab === 'fix-sequence' && <UcpFixSequence report={controller.report} />}
        </div>
      </div>

      {/* Drawer Overlay for Timeline History */}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={controller.resolvedJobId}
        onSelect={(id) => {
          const matched = controller.historyItems.find((j) => j.id === id);
          if (matched) controller.selectJob(matched);
        }}
        title="AI Discoverability Score Runs"
      />
    </div>
  );
}
