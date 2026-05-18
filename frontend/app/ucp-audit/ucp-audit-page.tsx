'use client';

import { useMemo, useState } from 'react';
import { Play, RefreshCcw, ShieldCheck, Layers, AlertTriangle, Eye, CheckSquare, History } from 'lucide-react';

import { InlineAlert, PageHeader } from '../../components/ui/patterns';
import { Button, Input, Toggle } from '../../components/ui/primitives';
import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';
import {
  UcpAgentViewPanel,
  UcpDimensionTable,
  UcpFindingsPanel,
  UcpFixSequence,
  UcpScoreSummary,
} from './ucp-audit-components';
import { useUcpAudit } from './use-ucp-audit';
import { cn } from '../../lib/utils';

export default function UcpAuditPage() {
  const controller = useUcpAudit();
  const [activeTab, setActiveTab] = useState<'compliance' | 'findings' | 'agent-delta' | 'fix-sequence'>('compliance');
  const [historyOpen, setHistoryOpen] = useState(false);

  const description =
    controller.activeJob && controller.report
      ? `${controller.activeJob.domain} · score ${controller.report.overall_score}`
      : 'Run deterministic UCP compliance checks against ecommerce domains.';

  const tabOptions = [
    { id: 'compliance', label: 'Compliance Index', icon: Layers },
    { id: 'findings', label: 'Findings Log', icon: AlertTriangle },
    { id: 'agent-delta', label: 'Fidelity Delta (D-UCP7)', icon: Eye },
    { id: 'fix-sequence', label: 'Repair Roadmap', icon: CheckSquare },
  ] as const;

  const historyItems: HistoryItem[] = useMemo(() => {
    return controller.historyItems.map((job) => ({
      id: job.id,
      status: job.status,
      created_at: job.created_at,
      label: job.domain,
      meta: job.summary?.overall_score != null ? `${job.summary.overall_score}/100 index` : 'Audit run queued',
    }));
  }, [controller.historyItems]);

  return (
    <div className="page-stack gap-5">
      <PageHeader
        title="UCP Audit"
        description={description}
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setHistoryOpen(true)}
              className="h-[var(--control-height)] border-border bg-panel text-foreground hover:bg-background-alt"
            >
              <History className="size-3.5" />
              History
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void controller.detailQuery.refetch()}
              disabled={!controller.resolvedJobId || controller.detailQuery.isFetching}
              className="h-[var(--control-height)] border-border bg-panel text-foreground hover:bg-background-alt"
            >
              <RefreshCcw className={cn("size-3.5", controller.detailQuery.isFetching && "animate-spin")} />
              Refresh
            </Button>
            <Button
              type="button"
              variant="accent"
              onClick={controller.startAudit}
              disabled={controller.createPending || controller.isRunning}
              className="h-[var(--control-height)] px-4"
            >
              <Play className="size-3.5" />
              {controller.createPending || controller.isRunning ? 'Auditing...' : 'Start Audit'}
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
      <section className="border-border bg-panel rounded-[var(--radius-lg)] border p-4 shadow-sm border-l-4 border-l-accent relative overflow-hidden">
        <div className="grid gap-4 sm:grid-cols-[1fr_140px_auto] sm:items-end">
          <label className="grid gap-1">
            <span className="field-label">Target Domain</span>
            <Input
              value={controller.domain}
              onChange={(event) => controller.setDomain(event.target.value)}
              placeholder="example-domain.com"
              className="font-mono text-sm h-[var(--control-height)] border-border focus:border-accent"
              aria-label="Domain"
            />
          </label>

          <label className="grid gap-1">
            <span className="field-label">Sample Size</span>
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
              className="h-[var(--control-height)] font-mono text-sm"
            />
          </label>

          <div className="border-border flex h-[var(--control-height)] items-center justify-between gap-3 rounded-[var(--radius-md)] border px-3 bg-background/30 min-w-[130px]">
            <span className="text-xs font-normal text-secondary">Agent Delta</span>
            <Toggle
              checked={Boolean(controller.options.include_agent_delta)}
              onChange={(value) =>
                controller.setOptions((current) => ({
                  ...current,
                  include_agent_delta: value,
                }))
              }
              ariaLabel="Toggle agent delta"
            />
          </div>
        </div>
      </section>

      {/* Full-Width Analytical Workspace Dashboard */}
      <div className="page-stack gap-5 w-full">
        {/* Overall Score & Dimension metrics */}
        <UcpScoreSummary report={controller.report} job={controller.activeJob} />

        {/* Workspace tab selectors */}
        <div className="border-border bg-panel flex flex-wrap gap-1 rounded-[var(--radius-lg)] border p-1 w-full">
          {tabOptions.map((tab) => {
            const TabIcon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'flex-1 min-w-[120px] flex items-center justify-center gap-2 py-2 px-3 text-xs font-normal rounded-[var(--radius-md)] transition-all cursor-pointer',
                  isActive
                    ? 'bg-accent text-accent-fg shadow-sm'
                    : 'text-muted hover:bg-background-alt hover:text-foreground'
                )}
              >
                <TabIcon className="size-3.5" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Tab viewports spanning full width */}
        <div className="animate-in fade-in duration-300 w-full min-w-0">
          {activeTab === 'compliance' && (
            <UcpDimensionTable
              report={controller.report}
              loading={controller.detailQuery.isLoading}
            />
          )}
          {activeTab === 'findings' && (
            <UcpFindingsPanel report={controller.report} />
          )}
          {activeTab === 'agent-delta' && (
            <UcpAgentViewPanel report={controller.report} />
          )}
          {activeTab === 'fix-sequence' && (
            <UcpFixSequence report={controller.report} />
          )}
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
        title="UCP Compliance Audit Runs"
      />
    </div>
  );
}
