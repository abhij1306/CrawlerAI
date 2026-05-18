'use client';

import { useState } from 'react';
import { Play, RefreshCcw, ShieldCheck, Layers, AlertTriangle, Eye, CheckSquare, AlertCircle } from 'lucide-react';

import { InlineAlert, PageHeader } from '../../components/ui/patterns';
import { Button, Input, Toggle } from '../../components/ui/primitives';
import {
  UcpAgentViewPanel,
  UcpDimensionTable,
  UcpFindingsPanel,
  UcpFixSequence,
  UcpHistoryList,
  UcpScoreSummary,
} from './ucp-audit-components';
import { useUcpAudit } from './use-ucp-audit';
import { cn } from '../../lib/utils';

export default function UcpAuditPage() {
  const controller = useUcpAudit();
  const [activeTab, setActiveTab] = useState<'compliance' | 'findings' | 'agent-delta' | 'fix-sequence'>('compliance');

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

      {/* Main Grid: Left Workbench (Tabs & Results), Right Configuration Panel & History */}
      <div className="grid min-h-0 gap-6 xl:grid-cols-[1fr_360px]">
        
        {/* Left Workbench Column */}
        <div className="page-stack gap-5 min-w-0">
          
          {/* Overall Compliance Header Score Summary Card */}
          <UcpScoreSummary report={controller.report} job={controller.activeJob} />

          {/* Workbench Tabs navigation */}
          <div className="border-border bg-panel flex flex-wrap gap-1 rounded-[var(--radius-lg)] border p-1">
            {tabOptions.map((tab) => {
              const TabIcon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    'flex-1 min-w-[120px] flex items-center justify-center gap-2 py-2 px-3 text-xs font-medium rounded-[var(--radius-md)] transition-all cursor-pointer',
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

          {/* Tab content viewport */}
          <div className="animate-in fade-in duration-300">
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

        {/* Right Sidebar Column (Setup & History) */}
        <aside className="page-stack gap-5 shrink-0">
          
          {/* Launcher Control Card */}
          <section className="border-border bg-panel rounded-[var(--radius-lg)] border p-4 shadow-sm flex flex-col gap-4">
            <header className="border-divider border-b pb-2 flex items-center gap-2">
              <ShieldCheck className="text-accent size-4 shrink-0" />
              <h2 className="text-xs font-bold font-mono tracking-widest text-muted uppercase">LAUNCH COMPLIANCE AUDIT</h2>
            </header>
            
            <div className="flex flex-col gap-3">
              <label className="grid gap-1">
                <span className="field-label">Target Domain</span>
                <Input
                  value={controller.domain}
                  onChange={(event) => controller.setDomain(event.target.value)}
                  placeholder="domain.com"
                  className="font-mono text-sm h-[var(--control-height)] border-border focus:border-accent"
                />
              </label>

              <div className="grid grid-cols-[1fr_auto] items-end gap-3">
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
                
                <div className="border-border flex h-[var(--control-height)] items-center justify-between gap-3 rounded-[var(--radius-md)] border px-3 bg-background/30 w-full min-w-[130px]">
                  <span className="text-xs font-semibold text-secondary">Agent Delta</span>
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
            </div>

            <Button
              type="button"
              variant="accent"
              onClick={controller.startAudit}
              disabled={controller.createPending || controller.isRunning}
              className="w-full h-10 mt-1 cursor-pointer flex justify-center gap-2 items-center text-sm font-semibold"
            >
              <Play className="size-3.5" />
              {controller.createPending || controller.isRunning ? 'Executing...' : 'Run Audit'}
            </Button>
          </section>

          {/* History Queue List */}
          <UcpHistoryList
            jobs={controller.historyItems}
            activeId={controller.resolvedJobId}
            onSelect={controller.selectJob}
          />
        </aside>
      </div>
    </div>
  );
}

