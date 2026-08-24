import { useEffect, useState } from 'react';
import { CheckCircle2, Trash2 } from 'lucide-react';

import { Button } from '@ui/primitives';
import { DetailRow, MutedPanelMessage, PageHeader, SectionCard } from '@ui/patterns';
import { Table, TableBody, TableHead, TableHeader, TableRow, TableCell } from '@ui/table';
import type { LlmConfigRecord, LlmCostLogRecord } from '@lib/api/admin';
import { LlmConfigFormCard } from './llm-config-form';
import { useAdminLlm } from './use-admin-llm';

// skipcq: JS-0067
export default function AdminLlmPage() {
  const {
    providers,
    configs,
    costLog,
    form,
    patchForm,
    customModelSelected,
    setCustomModelSelected,
    error,
    message,
    handleSave,
    handleTest,
    handleDelete,
    saving,
    testing,
  } = useAdminLlm();
  // Client-only "now" so today/yesterday labels don't differ between server and client render.
  const [nowMs, setNowMs] = useState<number | null>(null);
  useEffect(() => {
    const timeoutId = window.setTimeout(() => setNowMs(Date.now()), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <div className="page-stack">
      <PageHeader
        title="LLM Config"
        description="Restore runtime provider control for selector suggestion, cleanup review, and extraction fallback tasks."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        {/* ── Left column: create form + active configs */}
        <div className="page-stack">
          <LlmConfigFormCard
            form={form}
            providers={providers}
            customModelSelected={customModelSelected}
            testing={testing}
            saving={saving}
            message={message}
            error={error}
            onPatchForm={patchForm}
            onCustomModelSelected={setCustomModelSelected}
            onTest={handleTest}
            onSave={handleSave}
          />

          <ActiveConfigsCard configs={configs} onDelete={handleDelete} />
        </div>

        {/* ── Right column: cost log */}
        <CostLogCard costLog={costLog} nowMs={nowMs} />
      </div>
    </div>
  );
}

interface ActiveConfigsCardProps {
  configs: LlmConfigRecord[];
  onDelete: (id: number) => void;
}

function ActiveConfigsCard({ configs, onDelete }: Readonly<ActiveConfigsCardProps>) {
  return (
    <SectionCard
      title="Active Configs"
      description="The active runtime snapshot available to selector discovery and cleanup tasks."
      className="space-y-4"
    >
      {configs.length ? (
        <div className="space-y-3">
          {configs.map((config) => (
            <DetailRow key={config.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="type-control truncate !font-normal text-foreground">
                      {config.task_type}
                    </span>
                    {config.is_active ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-success-bg px-2 py-0.5 text-base leading-none font-normal text-success">
                        <CheckCircle2 className="size-3" aria-hidden="true" />
                        active
                      </span>
                    ) : null}
                  </div>
                  <p className="type-caption m-0">
                    {config.provider} · {config.model}
                  </p>
                  <p className="type-caption m-0">
                    {config.api_key_set ? config.api_key_masked : 'env-backed or unset'}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="destructive"
                  size="icon"
                  onClick={() => onDelete(config.id)}
                  aria-label="Delete config"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </DetailRow>
          ))}
        </div>
      ) : (
        <MutedPanelMessage title="No configs saved" description="No LLM configs saved yet." />
      )}
    </SectionCard>
  );
}

interface CostLogCardProps {
  costLog: LlmCostLogRecord[];
  nowMs: number | null;
}

function CostLogCard({ costLog, nowMs }: Readonly<CostLogCardProps>) {
  return (
    <div className="page-stack">
      <SectionCard
        title="Recent Cost Log"
        description="Latest LLM usage events recorded by the backend runtime."
        className="flex-1"
      >
        {costLog.length ? (
          <div className="custom-scrollbar max-h-[700px] overflow-y-auto">
            <Table className="table-auto">
              <TableHeader>
                <TableRow className="border-divider/50">
                  <TableHead className="w-[118px]">Usage</TableHead>
                  <TableHead className="w-[170px]">Task</TableHead>
                  <TableHead className="w-[160px]">Target</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead className="w-[110px] text-right">Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(() => {
                  const now = nowMs !== null ? new Date(nowMs) : null;
                  const todayStr = now?.toDateString();
                  const yesterdayStr = now
                    ? new Date(now.getTime() - 86_400_000).toDateString()
                    : undefined;
                  return costLog.slice(0, 40).map((entry) => {
                    const totalTokens = entry.input_tokens + entry.output_tokens;
                    const cost = parseFloat(entry.cost_usd) || 0;
                    return (
                      <TableRow key={entry.id} className="group transition-colors">
                        <TableCell className="py-3">
                          <div className="flex flex-col">
                            <div className="flex items-baseline gap-1.5">
                              <span className="type-caption-mono font-medium text-foreground tabular-nums">
                                {totalTokens.toLocaleString()}
                              </span>
                              <span className="type-caption">tokens</span>
                            </div>
                            <span className="type-label-mono mt-1 font-medium text-accent">
                              ${cost > 0 && cost < 0.0001 ? cost.toFixed(6) : cost.toFixed(4)}
                            </span>
                          </div>
                        </TableCell>

                        <TableCell className="py-3">
                          <span className="type-control block max-w-[150px] !font-normal whitespace-normal text-foreground">
                            {entry.task_type.replace(/_/g, ' ')}
                          </span>
                        </TableCell>

                        <TableCell className="py-3" title={entry.domain || `Run #${entry.run_id}`}>
                          <span className="block truncate text-foreground/80">
                            {entry.domain || (entry.run_id ? `Run #${entry.run_id}` : 'system')}
                          </span>
                        </TableCell>

                        <TableCell className="py-3">
                          <div className="flex flex-col overflow-hidden">
                            <span className="type-control truncate !font-normal text-foreground">
                              {entry.provider}
                            </span>
                            <span className="type-caption truncate" title={entry.model}>
                              {entry.model}
                            </span>
                          </div>
                        </TableCell>

                        <TableCell className="py-3 text-right">
                          <span className="type-caption-mono transition-colors group-hover:text-foreground">
                            {(() => {
                              const d = new Date(entry.created_at);
                              const dStr = d.toDateString();
                              const isToday = dStr === todayStr;
                              const isYesterday = dStr === yesterdayStr;

                              const timeStr = d.toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                hour12: false,
                              });
                              const dateStr = d.toLocaleDateString('en-US', {
                                month: '2-digit',
                                day: '2-digit',
                              });

                              if (isToday) return timeStr;
                              if (isYesterday) return `Yesterday ${timeStr}`;
                              return `${dateStr} ${timeStr}`;
                            })()}
                          </span>
                        </TableCell>
                      </TableRow>
                    );
                  });
                })()}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div className="p-12 text-center">
            <MutedPanelMessage
              title="No cost events"
              description="Detailed LLM usage and token metrics will appear here once active."
            />
          </div>
        )}
      </SectionCard>
    </div>
  );
}
