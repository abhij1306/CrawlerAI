import { AlertTriangle, CheckCircle2, GitBranch, RefreshCcw, Stethoscope } from 'lucide-react';
import { useMemo, useState } from 'react';

import type {
  DiagnoseField,
  ResultDiagnosis,
  KnowledgeContract,
  KnowledgeGraphResponse,
  KnowledgeSiteRecord,
  RunReportRootCause,
} from '../../../lib/api/types';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  KVTile,
  SurfaceSection,
} from '../../ui/patterns';
import { Badge, Button, Dropdown } from '../../ui/primitives';
import type { DomainWorkspace } from './types';
import { useKnowledgeGraph } from './use-knowledge-graph';
import { parseUrlResultId, useResultDiagnosis, useRunReport } from './use-run-diagnostics';
import { knowledgeFieldLabel, knowledgeSourceOptions, surfaceLabel, titleCaseToken } from './utils';

type KnowledgeGraphTabProps = {
  selectedWorkspace: DomainWorkspace;
};

type OriginDescriptor = {
  label: string;
  tone: 'accent' | 'info' | 'neutral';
};

export function KnowledgeGraphTab({ selectedWorkspace }: KnowledgeGraphTabProps) {
  const { query, selectSource } = useKnowledgeGraph(selectedWorkspace);
  const data = query.data ?? null;
  const site = scopedSite(data?.site, selectedWorkspace);
  const graphVersion = site?.current_version ?? null;
  const diagnosticsRunId = resolveDiagnosticsRunId(site, selectedWorkspace);

  const mutationError = selectSource.error
    ? selectSource.error instanceof Error
      ? selectSource.error.message
      : 'Unable to update source selection.'
    : '';
  const loadError = query.error
    ? query.error instanceof Error
      ? query.error.message
      : 'Unable to load Knowledge Graph.'
    : '';

  function runSelect(contract: KnowledgeContract, selectedSource: string) {
    if (!selectedSource) return;
    selectSource.mutate({ contract, selectedSource, expectedVersion: graphVersion });
  }

  return (
    <SurfaceSection
      title="Knowledge Graph"
      description="Per-field source reliability, operator contracts, and run diagnostics root-cause."
      icon={GitBranch}
      action={
        <Button
          type="button"
          variant="neutral"
          size="sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCcw className="size-3" />
          {query.isFetching ? 'Refreshing...' : 'Refresh'}
        </Button>
      }
      bodyClassName="space-y-5"
    >
      {loadError ? <DataRegionError message={loadError} className="p-0" /> : null}
      {mutationError ? <DataRegionError message={mutationError} className="p-0" /> : null}
      {query.isLoading ? (
        <DataRegionLoading count={6} className="p-0" />
      ) : data && data.graph.nodes.length ? (
        <>
          <GraphSummary site={site} graph={data.graph} contracts={data.contracts} />
          <SourceReliability contracts={data.contracts} />
          <ContractPanel
            contracts={data.contracts}
            pendingContractId={
              selectSource.isPending ? (selectSource.variables?.contract.id ?? '') : ''
            }
            savedContractId={
              selectSource.isSuccess ? (selectSource.variables?.contract.id ?? '') : ''
            }
            onSelectSource={runSelect}
          />
          <DiagnosticsDrillDown runId={diagnosticsRunId} />
        </>
      ) : (
        <DataRegionEmpty
          title="No graph for this domain"
          description="Projection creates graph nodes after completed crawls or accepted selector contracts."
          className="p-0"
        />
      )}
    </SurfaceSection>
  );
}

function GraphSummary({
  site,
  graph,
  contracts,
}: {
  site: KnowledgeSiteRecord | null;
  graph: KnowledgeGraphResponse;
  contracts: KnowledgeContract[];
}) {
  const operatorContracts = contracts.filter((c) => c.selection_origin === 'operator').length;
  const metrics = [
    { label: 'Version', value: site?.current_version ?? '0' },
    { label: 'Status', value: titleCaseToken(site?.projection_status ?? 'unknown') },
    { label: 'Entities', value: graph.nodes.length },
    { label: 'Operator contracts', value: operatorContracts },
  ];
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {metrics.map((metric) => (
        <KVTile key={metric.label} label={metric.label} value={metric.value} />
      ))}
    </div>
  );
}

type FieldReliability = {
  field: string;
  group: string;
  label: string;
  success: number;
  rejection: number;
  ratio: number;
};

function SourceReliability({ contracts }: { contracts: KnowledgeContract[] }) {
  const rows = useMemo(() => aggregateReliability(contracts), [contracts]);
  if (!rows.length) return null;
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Source reliability</h3>
        <p className="mt-1 text-xs text-muted">
          Accepted vs rejected observations per field across the crawl
        </p>
      </div>
      <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
        {rows.map((row) => (
          <div
            key={row.field}
            className="grid items-center gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto_120px]"
          >
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-medium text-foreground">{row.label}</span>
              <Badge tone="neutral">{row.group}</Badge>
            </div>
            <div className="text-xs text-muted">
              {row.success} accepted · {row.rejection} rejected
            </div>
            <div className="flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-background-alt">
                <div
                  className={reliabilityBarClass(row.ratio)}
                  style={{ width: `${Math.round(row.ratio * 100)}%` }}
                />
              </div>
              <span className="w-9 shrink-0 text-right text-xs font-medium text-secondary">
                {Math.round(row.ratio * 100)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ContractPanel({
  contracts,
  pendingContractId,
  savedContractId,
  onSelectSource,
}: {
  contracts: KnowledgeContract[];
  pendingContractId: string;
  savedContractId: string;
  onSelectSource: (contract: KnowledgeContract, selectedSource: string) => void;
}) {
  if (!contracts.length) {
    return (
      <DataRegionEmpty
        title="No source contracts"
        description="Accepted source candidates appear here after projection or saved generated selectors."
        className="p-0"
      />
    );
  }
  const grouped = groupContractsByTemplate(contracts);
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Extraction preferences</h3>
        <p className="mt-1 text-xs text-muted">
          Preferred source for future matching runs. AI-suggested sources stay inert until promoted.
        </p>
      </div>
      {grouped.map(([templateId, templateContracts]) => (
        <section key={templateId} className="overflow-hidden rounded-lg border border-border">
          <header className="flex flex-wrap items-center justify-between gap-3 bg-background-alt px-4 py-3">
            <div className="text-xs font-medium text-foreground">
              {surfaceLabel(templateContracts[0].surface)}
            </div>
            <Badge tone="neutral">{templateContracts.length} fields</Badge>
          </header>
          <div className="divide-y divide-border">
            {templateContracts.map((contract) => (
              <ContractPreferenceRow
                key={contract.id}
                contract={contract}
                pending={pendingContractId === contract.id}
                saved={savedContractId === contract.id}
                onSelectSource={onSelectSource}
              />
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}

function ContractPreferenceRow({
  contract,
  pending,
  saved,
  onSelectSource,
}: {
  contract: KnowledgeContract;
  pending: boolean;
  saved: boolean;
  onSelectSource: (contract: KnowledgeContract, selectedSource: string) => void;
}) {
  const field = knowledgeFieldLabel(contract.canonical_field);
  const sourceOptions = knowledgeSourceOptions(contract);
  const selected =
    sourceOptions.find((option) => option.value === contract.selected_source) ?? sourceOptions[0];
  const origin = originDescriptor(contract.selection_origin);
  const isProposed = contract.selection_origin === 'llm_proposed';

  return (
    <div className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{field.label}</span>
          <Badge tone="neutral">{field.group}</Badge>
          <Badge tone={origin.tone}>{origin.label}</Badge>
          {saved ? (
            <span className="flex items-center gap-1 text-xs font-medium text-success">
              <CheckCircle2 className="size-3.5" /> Saved
            </span>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          <span>{contract.success_count} accepted</span>
          <span>{contract.rejection_count} rejected</span>
          {isProposed && selected ? (
            <Button
              type="button"
              variant="neutral"
              size="sm"
              disabled={pending}
              onClick={() => onSelectSource(contract, selected.value)}
            >
              Promote to manual
            </Button>
          ) : null}
        </div>
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 text-xs font-medium text-secondary">Preferred source</div>
        {sourceOptions.length > 1 && selected ? (
          <Dropdown<string>
            value={selected.value}
            onChange={(value) => {
              if (value !== contract.selected_source) onSelectSource(contract, value);
            }}
            options={sourceOptions.map((source) => ({ value: source.value, label: source.label }))}
            ariaLabel={`Source for ${contract.canonical_field}`}
            disabled={pending}
          />
        ) : selected ? (
          <div className="flex min-h-[var(--control-height)] items-center justify-between gap-3 rounded-md border border-border bg-panel px-3 py-2">
            <span className="min-w-0 truncate text-xs text-foreground">{selected.label}</span>
            <span className="shrink-0 text-xs text-muted">Only observed source</span>
          </div>
        ) : (
          <div className="text-xs text-muted">No usable source observed</div>
        )}
        {selected?.locator ? (
          <div className="mt-1.5 truncate font-mono text-xs text-muted" title={selected.locator}>
            {selected.locator}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function DiagnosticsDrillDown({ runId }: { runId: number | null }) {
  const report = useRunReport(runId);
  const [expanded, setExpanded] = useState<string>('');

  if (runId == null) {
    return (
      <DataRegionEmpty
        title="No diagnosable run"
        description="Diagnostics appear after a completed crawl projects into this domain's graph."
        className="p-0"
      />
    );
  }

  const rootCauses = report.data?.root_causes ?? [];
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Stethoscope className="size-4 text-muted" />
        <h3 className="text-sm font-semibold text-foreground">Run diagnostics</h3>
        <span className="text-xs text-muted">Run #{runId}</span>
      </div>
      {report.isLoading ? (
        <DataRegionLoading count={3} className="p-0" />
      ) : report.error ? (
        <DataRegionError
          message={
            report.error instanceof Error ? report.error.message : 'Unable to load run report.'
          }
          className="p-0"
        />
      ) : rootCauses.length ? (
        <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
          {rootCauses.map((cause) => (
            <RootCauseRow
              key={cause.root_cause}
              runId={runId}
              cause={cause}
              expanded={expanded === cause.root_cause}
              onToggle={() =>
                setExpanded((current) => (current === cause.root_cause ? '' : cause.root_cause))
              }
            />
          ))}
        </div>
      ) : (
        <DataRegionEmpty
          title="No root causes"
          description="Every field resolved cleanly across this run — nothing to diagnose."
          className="p-0"
        />
      )}
    </section>
  );
}

function RootCauseRow({
  runId,
  cause,
  expanded,
  onToggle,
}: {
  runId: number;
  cause: RunReportRootCause;
  expanded: boolean;
  onToggle: () => void;
}) {
  const firstLink = cause.diagnose_links[0] ?? '';
  const urlResultId = parseUrlResultId(firstLink);
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-background-alt"
        aria-expanded={expanded}
      >
        <span className="flex min-w-0 items-center gap-2">
          <AlertTriangle className="size-3.5 shrink-0 text-warning" />
          <span className="truncate font-mono text-xs text-foreground">{cause.root_cause}</span>
        </span>
        <Badge tone="warning">
          {cause.count} {cause.count === 1 ? 'page' : 'pages'}
        </Badge>
      </button>
      {expanded ? (
        <RootCauseDetail runId={runId} urlResultId={urlResultId} link={firstLink} />
      ) : null}
    </div>
  );
}

function RootCauseDetail({
  runId,
  urlResultId,
  link,
}: {
  runId: number;
  urlResultId: number | null;
  link: string;
}) {
  const diagnosis = useResultDiagnosis(runId, urlResultId, true);
  if (urlResultId == null) {
    return <div className="px-4 pb-3 text-xs text-muted">Diagnose artifact link unavailable.</div>;
  }
  if (diagnosis.isLoading) {
    return <DataRegionLoading count={2} className="px-4 pb-3" />;
  }
  if (diagnosis.error || !diagnosis.data) {
    return (
      <div className="px-4 pb-3 text-xs text-muted">
        No diagnose artifact persisted for {link || 'this page'}.
      </div>
    );
  }
  const fields = diagnosis.data.fields.filter((field) => isProblemField(field));
  return (
    <div className="space-y-2 bg-background-alt px-4 py-3">
      <div className="text-2xs tracking-wide text-muted uppercase">
        {diagnosis.data.verdict ? `Verdict: ${titleCaseToken(diagnosis.data.verdict)}` : 'Fields'}
      </div>
      <EvidenceDispositionSummary diagnosis={diagnosis.data} />
      {fields.length ? (
        fields.map((field) => <DiagnoseFieldRow key={field.field} field={field} />)
      ) : (
        <div className="text-xs text-muted">No field-level failures recorded on this page.</div>
      )}
    </div>
  );
}

function EvidenceDispositionSummary({ diagnosis }: { diagnosis: ResultDiagnosis }) {
  const summary = diagnosis.evidence_dispositions;
  if (!summary || !summary.total) return null;
  const rows = Object.entries(summary.by_status ?? {})
    .filter(([, count]) => Number(count) > 0)
    .sort(([left], [right]) => left.localeCompare(right));
  if (!rows.length) return null;
  return (
    <div className="text-2xs rounded-md border border-border bg-muted/20 px-3 py-2 text-muted">
      <div className="font-semibold text-foreground">Evidence accounting: {summary.total}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {rows.map(([status, count]) => (
          <Badge key={status} tone={dispositionTone(status)}>
            {titleCaseToken(status)} {count}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function DiagnoseFieldRow({ field }: { field: DiagnoseField }) {
  const publicationPolicy = field.publication_policy;
  return (
    <div className="rounded-md border border-border bg-panel px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-foreground">{titleCaseToken(field.field)}</span>
        <Badge tone={fieldTone(field.status)}>{titleCaseToken(field.status)}</Badge>
        {publicationPolicy != null && publicationPolicy !== '' ? (
          <Badge tone="danger">Publication policy</Badge>
        ) : null}
      </div>
      {field.winner?.value != null ? (
        <div
          className="text-2xs mt-1 truncate font-mono text-muted"
          title={String(field.winner.value)}
        >
          winner: {String(field.winner.value)}
        </div>
      ) : null}
      {field.rejected?.length ? (
        <div className="text-2xs mt-1 text-muted">
          {field.rejected.length} rejected candidate{field.rejected.length === 1 ? '' : 's'}
          {field.rejected[0]?.reason ? ` · ${field.rejected[0].reason}` : ''}
        </div>
      ) : null}
    </div>
  );
}

// --- helpers ---------------------------------------------------------------

function aggregateReliability(contracts: KnowledgeContract[]): FieldReliability[] {
  const byField = new Map<string, FieldReliability>();
  for (const contract of contracts) {
    const key = contract.canonical_field;
    const label = knowledgeFieldLabel(key);
    const entry =
      byField.get(key) ??
      ({
        field: key,
        group: label.group,
        label: label.label,
        success: 0,
        rejection: 0,
        ratio: 0,
      } satisfies FieldReliability);
    entry.success += contract.success_count ?? 0;
    entry.rejection += contract.rejection_count ?? 0;
    byField.set(key, entry);
  }
  const rows = Array.from(byField.values()).filter((row) => row.success + row.rejection > 0);
  for (const row of rows) {
    row.ratio = row.success / (row.success + row.rejection);
  }
  rows.sort((a, b) => a.ratio - b.ratio || a.label.localeCompare(b.label));
  return rows;
}

function reliabilityBarClass(ratio: number) {
  const tone = ratio >= 0.85 ? 'bg-success' : ratio >= 0.5 ? 'bg-warning' : 'bg-danger';
  return `h-full ${tone}`;
}

function originDescriptor(origin: string): OriginDescriptor {
  if (origin === 'operator') return { label: 'Manual', tone: 'accent' };
  if (origin === 'llm_proposed') return { label: 'AI suggested', tone: 'info' };
  return { label: 'Automatic', tone: 'neutral' };
}

function isProblemField(field: DiagnoseField) {
  if (field.publication_policy != null && field.publication_policy !== '') return true;
  return (
    Boolean(field.status) &&
    !['captured_and_resolved', 'captured_published', 'not_requested'].includes(field.status)
  );
}

function fieldTone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'captured_and_resolved' || status === 'captured_published') return 'success';
  if (
    status.includes('rejected') ||
    status.includes('missing') ||
    status === 'captured_conflicting'
  )
    return 'danger';
  if (status === 'not_found' || status === 'not_present_in_source') return 'neutral';
  return 'warning';
}

function dispositionTone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'accepted') return 'success';
  if (status === 'rejected_invalid' || status === 'conflicted') return 'danger';
  if (status === 'rejected_lower_rank' || status === 'duplicate') return 'neutral';
  return 'warning';
}

function groupContractsByTemplate(contracts: KnowledgeContract[]) {
  const groups = new Map<string, KnowledgeContract[]>();
  for (const contract of contracts) {
    const group = groups.get(contract.template_id) ?? [];
    group.push(contract);
    groups.set(contract.template_id, group);
  }
  return Array.from(groups.entries());
}

function scopedSite(
  stateSite: KnowledgeSiteRecord | null | undefined,
  workspace: DomainWorkspace,
): KnowledgeSiteRecord | null {
  const fromState = stateSite?.domain === workspace.domain ? stateSite : null;
  const fromWorkspace =
    workspace.knowledgeSite?.domain === workspace.domain ? workspace.knowledgeSite : null;
  if (!fromState) return fromWorkspace;
  if (!fromWorkspace) return fromState;
  return fromWorkspace.current_version > fromState.current_version ? fromWorkspace : fromState;
}

function resolveDiagnosticsRunId(
  site: KnowledgeSiteRecord | null,
  workspace: DomainWorkspace,
): number | null {
  if (site?.last_projected_run_id) return site.last_projected_run_id;
  const runIds = workspace.surfaces.flatMap((surface) =>
    surface.completedRuns.map((run) => run.id),
  );
  return runIds.length ? Math.max(...runIds) : null;
}
