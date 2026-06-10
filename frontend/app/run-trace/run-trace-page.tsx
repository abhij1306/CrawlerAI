'use client';

import { useState, type FormEventHandler } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown) {
  switch (typeof value) {
    case 'undefined':
      return undefined;
    case 'string':
      return value;
    default:
      return null;
  }
}

function optionalRecord(value: unknown) {
  if (value === undefined) return undefined;
  return isRecord(value) ? value : null;
}

function runDiagnosisFromRecord(value: Record<string, unknown>) {
  const status = optionalString(value.status);
  const diagnosis = optionalRecord(value.diagnosis);
  if (status === null || diagnosis === null) return null;
  return { status, diagnosis };
}

function readRunDiagnosis(value: unknown) {
  if (!isRecord(value)) return null;
  return runDiagnosisFromRecord(value);
}

function jsonDisplayValue(value: unknown, fallback: string) {
  try {
    return JSON.stringify(value) ?? fallback;
  } catch {
    return fallback;
  }
}

function nonNullDisplayValue(value: unknown, fallback: string) {
  switch (typeof value) {
    case 'string':
      return value;
    case 'number':
    case 'boolean':
      return String(value);
    default:
      return jsonDisplayValue(value, fallback);
  }
}

function displayValue(value: unknown, fallback = '') {
  return value == null ? fallback : nonNullDisplayValue(value, fallback);
}

function firstCodePoint(value: string) {
  return value.codePointAt(0) ?? 0;
}

function stableHash(value: unknown): string {
  const text = JSON.stringify(value) ?? '';
  let hash = 0;
  for (const character of text) {
    hash = (hash * 31 + firstCodePoint(character)) % 2147483647;
  }
  return hash.toString(36);
}

function traceKey(trace: RunTraceArtifact): string {
  const traceId = (trace as RunTraceArtifact & { id?: unknown }).id;
  if (typeof traceId === 'string' || typeof traceId === 'number') {
    return `${trace.run_id}:${traceId}`;
  }
  return `${trace.run_id}:${trace.url}:${trace.surface}:${trace.tier}:${stableHash(trace)}`;
}

type TimelineDisplayEvent = {
  key: string;
  sequence: string;
  label: string;
  duration_ms?: number;
  detail?: string;
};

function formatAcquireTimeline(trace: RunTraceArtifact): TimelineDisplayEvent[] {
  const result: TimelineDisplayEvent[] = [];
  let index = 0;
  while (index < trace.acquire_timeline.length) {
    const event = trace.acquire_timeline[index];
    if (event.kind !== 'readiness_probe') {
      result.push({
        key: String(event.sequence),
        sequence: String(event.sequence),
        label: event.kind,
        duration_ms: event.duration_ms,
      });
      index += 1;
      continue;
    }

    const group = [event];
    index += 1;
    while (trace.acquire_timeline[index]?.kind === 'readiness_probe') {
      group.push(trace.acquire_timeline[index]);
      index += 1;
    }
    const first = group[0];
    const last = group.at(-1) ?? first;
    const firstStage = displayValue(first.detail?.stage);
    const lastStage = displayValue(last.detail?.stage);
    const detailParts = [
      firstStage && lastStage && firstStage !== lastStage
        ? `${firstStage} -> ${lastStage}`
        : lastStage,
      `ready=${displayValue(last.detail?.is_ready, 'unknown')}`,
      `detail=${displayValue(last.detail?.detail_like, 'unknown')}`,
    ].filter(Boolean);
    result.push({
      key: `${first.sequence}-${last.sequence}`,
      sequence: group.length === 1 ? String(first.sequence) : `${first.sequence}-${last.sequence}`,
      label: group.length === 1 ? 'readiness_probe' : `readiness_probe x${group.length}`,
      detail: detailParts.join(' | '),
    });
  }
  return result;
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
  const timeline = formatAcquireTimeline(trace);
  const hasTimeline = timeline.length > 0;
  const domSkipped = trace.extraction.dom_skipped;
  const showDomSkipped = typeof domSkipped === 'boolean';
  const domCompletionReason = displayValue(trace.extraction.skip_decision?.dom_completion_reason);
  const fieldProvenance = trace.extraction.field_provenance ?? [];
  const hasFieldProvenance = fieldProvenance.length > 0;

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
        <h4 className="type-subheading">Acquire timeline</h4>
        <ol className="mt-1 flex flex-col gap-1">
          {hasTimeline ? (
            timeline.map((event) => (
              <li key={event.key} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted font-mono">{event.sequence}.</span>
                <span className="font-medium">{event.label}</span>
                {event.duration_ms != null ? (
                  <span className="text-muted">{event.duration_ms}ms</span>
                ) : null}
                {event.detail ? <span className="text-muted">{event.detail}</span> : null}
              </li>
            ))
          ) : (
            <li className="text-muted text-xs">No acquire events recorded.</li>
          )}
        </ol>
      </div>

      <div>
        <h4 className="type-subheading">Extraction</h4>
        <p className="mt-1 text-xs">
          Tiers:{' '}
          <span className="font-mono">{trace.extraction.completed_tiers.join(' → ') || '—'}</span>
        </p>
        {showDomSkipped ? (
          <p className="text-xs">
            DOM skipped: <span className="font-mono">{String(domSkipped)}</span>
            {domCompletionReason ? ` (${domCompletionReason})` : ''}
          </p>
        ) : null}
        {trace.extraction.rejection_reason ? (
          <p className="text-xs">
            Rejection: <span className="font-mono">{trace.extraction.rejection_reason}</span>
          </p>
        ) : null}
        {hasFieldProvenance ? (
          <ul className="mt-1 flex flex-col gap-1">
            {fieldProvenance.map((entry) => (
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
  const queryClient = useQueryClient();
  const [runIdInput, setRunIdInput] = useState('');
  const [data, setData] = useState<RunObservability | null>(null);

  const lookup = useMutation({
    mutationFn: (runId: number) => api.getRunObservability(runId),
    onSuccess: (result, runId) => {
      queryClient.setQueryData(['run-observability', runId], result);
      setData(result);
    },
  });

  const onSubmit: FormEventHandler<HTMLFormElement> = (event) => {
    event.preventDefault();
    const runId = Number.parseInt(runIdInput, 10);
    if (Number.isFinite(runId) && runId > 0) {
      lookup.mutate(runId);
    }
  };

  const notFound = httpErrorStatus(lookup.error) === 404;
  const diagnosis = readRunDiagnosis(data?.llm_diagnosis);
  const flags = data?.flags ?? null;
  const hasFlags = (flags?.flags.length ?? 0) > 0;
  const hasFlagCount = typeof flags?.flag_count === 'number';
  const traces = data?.traces ?? [];
  const hasTraces = traces.length > 0;

  return (
    <div className="page-stack gap-5">
      <PageHeader
        title="Run Trace"
        description="Inspect the acquire timeline, extraction tiers, and auto-flagged bugs for a run. Read-only."
      />

      <form onSubmit={onSubmit} className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="run-id" className="field-label">
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
            <h3 className="type-heading-3 flex items-center gap-2">
              <Network className="size-4" /> Flags
              {hasFlagCount ? <Badge tone="neutral">{flags?.flag_count}</Badge> : null}
            </h3>
            {hasFlags ? (
              <div className="grid gap-3 md:grid-cols-2">
                {flags?.flags.map((flag) => (
                  <FlagCard key={`${flag.code}-${flag.symptom}-${flag.url ?? ''}`} flag={flag} />
                ))}
              </div>
            ) : (
              <InlineAlert tone="neutral" message="No bugs flagged for this run." />
            )}
          </section>

          {diagnosis && diagnosis.status === 'ok' && diagnosis.diagnosis ? (
            <section className="flex flex-col gap-2">
              <h3 className="type-heading-3">LLM diagnosis</h3>
              <Card className="p-4">
                <pre className="overflow-x-auto text-xs">
                  {JSON.stringify(diagnosis.diagnosis, null, 2)}
                </pre>
              </Card>
            </section>
          ) : null}

          <section className="flex flex-col gap-2">
            <h3 className="type-heading-3">Traces ({traces.length})</h3>
            {hasTraces ? (
              <div className="flex flex-col gap-3">
                {traces.map((trace) => (
                  <TraceCard key={traceKey(trace)} trace={trace} />
                ))}
              </div>
            ) : (
              <InlineAlert tone="neutral" message="No per-URL traces found for this run." />
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
