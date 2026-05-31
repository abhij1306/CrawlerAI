'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Network, Search } from 'lucide-react';

import { InlineAlert, PageHeader } from '../../components/ui/patterns';
import { Badge, Button, Card, Input } from '../../components/ui/primitives';
import { api } from '../../lib/api';
import { httpErrorStatus } from '../../lib/api/client';
import type { RunAuditFlag, RunObservability, RunTraceArtifact } from '../../lib/api/types';

function severityTone(severity: string): 'danger' | 'warning' | 'neutral' {
  if (severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  return 'neutral';
}

function FlagCard({ flag }: Readonly<{ flag: RunAuditFlag }>) {
  return (
    <Card className="flex flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm">{flag.code}</span>
        <Badge tone={severityTone(flag.severity)}>{flag.severity}</Badge>
      </div>
      <p className="text-muted text-sm">{flag.symptom}</p>
      {flag.invariant ? <p className="text-muted text-xs">Invariant: {flag.invariant}</p> : null}
      {flag.owner ? (
        <p className="text-xs">
          Owner: <span className="font-mono">{flag.owner}</span>
        </p>
      ) : null}
      {flag.url ? <p className="text-muted text-xs break-all">{flag.url}</p> : null}
      {flag.evidence ? (
        <pre className="bg-background-alt overflow-x-auto rounded p-2 text-xs">
          {JSON.stringify(flag.evidence, null, 2)}
        </pre>
      ) : null}
    </Card>
  );
}

function TraceCard({ trace }: Readonly<{ trace: RunTraceArtifact }>) {
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{trace.surface || 'unknown surface'}</Badge>
        <Badge tone={trace.verdict === 'success' ? 'success' : 'warning'}>
          {trace.verdict || 'no verdict'}
        </Badge>
        <Badge tone="neutral">tier: {trace.tier}</Badge>
        <span className="text-muted text-xs break-all">{trace.url}</span>
      </div>

      <div>
        <h4 className="text-sm font-semibold">Acquire timeline</h4>
        <ol className="mt-1 flex flex-col gap-1">
          {trace.acquire_timeline.length === 0 ? (
            <li className="text-muted text-xs">No acquire events recorded.</li>
          ) : (
            trace.acquire_timeline.map((event) => (
              <li key={event.sequence} className="flex items-center gap-2 text-xs">
                <span className="text-muted font-mono">{event.sequence}.</span>
                <span className="font-medium">{event.kind}</span>
                {event.duration_ms != null ? (
                  <span className="text-muted">{event.duration_ms}ms</span>
                ) : null}
              </li>
            ))
          )}
        </ol>
      </div>

      <div>
        <h4 className="text-sm font-semibold">Extraction</h4>
        <p className="mt-1 text-xs">
          Tiers:{' '}
          <span className="font-mono">{trace.extraction.completed_tiers.join(' → ') || '—'}</span>
        </p>
        {trace.extraction.dom_skipped != null ? (
          <p className="text-xs">
            DOM skipped: <span className="font-mono">{String(trace.extraction.dom_skipped)}</span>
            {trace.extraction.skip_decision?.dom_completion_reason
              ? ` (${String(trace.extraction.skip_decision.dom_completion_reason)})`
              : ''}
          </p>
        ) : null}
        {trace.extraction.field_provenance && trace.extraction.field_provenance.length > 0 ? (
          <ul className="mt-1 flex flex-col gap-1">
            {trace.extraction.field_provenance.map((entry) => (
              <li key={entry.field} className="text-xs">
                <span className="font-medium">{entry.field}</span>
                {entry.winning_source ? (
                  <span className="text-muted"> ← {entry.winning_source}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  );
}

export default function RunTracePage() {
  const [runIdInput, setRunIdInput] = useState('');
  const [data, setData] = useState<RunObservability | null>(null);

  const lookup = useMutation({
    mutationFn: (runId: number) => api.getRunObservability(runId),
    onSuccess: (result) => setData(result),
  });

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const runId = Number.parseInt(runIdInput, 10);
    if (Number.isFinite(runId) && runId > 0) {
      lookup.mutate(runId);
    }
  };

  const notFound = httpErrorStatus(lookup.error) === 404;
  const diagnosis = data?.llm_diagnosis as
    | { status?: string; diagnosis?: Record<string, unknown> }
    | null
    | undefined;

  return (
    <div className="page-stack gap-5">
      <PageHeader
        title="Run Trace"
        description="Inspect the acquire timeline, extraction tiers, and auto-flagged bugs for a run. Read-only."
      />

      <form onSubmit={onSubmit} className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="run-id" className="text-xs font-medium">
            Run ID
          </label>
          <Input
            id="run-id"
            inputMode="numeric"
            placeholder="e.g. 33"
            value={runIdInput}
            onChange={(event) => setRunIdInput(event.target.value)}
            className="w-40"
          />
        </div>
        <Button type="submit" disabled={lookup.isPending}>
          <Search className="size-4" />
          {lookup.isPending ? 'Loading…' : 'Load run'}
        </Button>
      </form>

      {notFound ? <InlineAlert tone="warning" message="Run not found or not accessible." /> : null}
      {lookup.isError && !notFound ? (
        <InlineAlert tone="danger" message="Could not load run observability." />
      ) : null}

      {data ? (
        <>
          <section className="flex flex-col gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Network className="size-4" /> Flags
              {data.flags ? <Badge tone="neutral">{data.flags.flag_count}</Badge> : null}
            </h3>
            {!data.flags || data.flags.flags.length === 0 ? (
              <InlineAlert tone="neutral" message="No bugs flagged for this run." />
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {data.flags.flags.map((flag, index) => (
                  <FlagCard key={`${flag.code}-${index}`} flag={flag} />
                ))}
              </div>
            )}
          </section>

          {diagnosis && diagnosis.status === 'ok' && diagnosis.diagnosis ? (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">LLM diagnosis</h3>
              <Card className="p-4">
                <pre className="overflow-x-auto text-xs">
                  {JSON.stringify(diagnosis.diagnosis, null, 2)}
                </pre>
              </Card>
            </section>
          ) : null}

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Traces ({data.traces.length})</h3>
            {data.traces.length === 0 ? (
              <InlineAlert tone="neutral" message="No per-URL traces found for this run." />
            ) : (
              <div className="flex flex-col gap-3">
                {data.traces.map((trace, index) => (
                  <TraceCard key={`${trace.url}-${index}`} trace={trace} />
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
