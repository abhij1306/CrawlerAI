import { CheckCircle2, RefreshCcw, SlidersHorizontal } from 'lucide-react';

import type { KnowledgeContract, KnowledgeSiteRecord } from '@lib/api/knowledge';
import { surfaceLabel } from '@lib/format/domain';
import { DataRegionEmpty, DataRegionError, DataRegionLoading, SurfaceSection } from '@ui/patterns';
import { Badge, Button, Dropdown } from '@ui/primitives';
import type { DomainWorkspace } from './types';
import { useKnowledgeGraph } from './use-knowledge-graph';
import { knowledgeFieldLabel, knowledgeSourceOptions } from './utils';

type KnowledgeGraphTabProps = {
  selectedWorkspace: DomainWorkspace;
};

type OriginDescriptor = {
  label: string;
  tone: 'accent' | 'info' | 'neutral';
};

function queryErrorMessage(error: unknown, fallback: string) {
  if (!error) return '';
  return error instanceof Error ? error.message : fallback;
}

function mutationContractId(
  enabled: boolean,
  variables: { contract: KnowledgeContract } | undefined,
) {
  return enabled ? (variables?.contract.id ?? '') : '';
}

export function KnowledgeGraphTab({ selectedWorkspace }: KnowledgeGraphTabProps) {
  const { query, selectSource } = useKnowledgeGraph(selectedWorkspace);
  const data = query.data ?? null;
  const site = scopedSite(data?.site, selectedWorkspace);
  const graphVersion = site?.current_version ?? null;

  const mutationError = queryErrorMessage(
    selectSource.error,
    'Unable to update extraction preference.',
  );
  const loadError = queryErrorMessage(query.error, 'Unable to load extraction preferences.');
  const contracts = data?.contracts ?? [];

  function runSelect(contract: KnowledgeContract, selectedSource: string) {
    if (!selectedSource) return;
    selectSource.mutate({ contract, selectedSource, expectedVersion: graphVersion });
  }

  return (
    <SurfaceSection
      title="Extraction preferences"
      description="Domain defaults for future crawls, scoped by surface and field—not by individual URL."
      icon={SlidersHorizontal}
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
        <DataRegionLoading count={5} className="p-0" />
      ) : (
        <>
          <PreferenceScope domain={selectedWorkspace.domain} site={site} contracts={contracts} />
          <ContractPanel
            contracts={contracts}
            pendingContractId={mutationContractId(selectSource.isPending, selectSource.variables)}
            savedContractId={mutationContractId(selectSource.isSuccess, selectSource.variables)}
            onSelectSource={runSelect}
          />
        </>
      )}
    </SurfaceSection>
  );
}

function PreferenceScope({
  domain,
  site,
  contracts,
}: {
  domain: string;
  site: KnowledgeSiteRecord | null;
  contracts: KnowledgeContract[];
}) {
  const surfaces = new Set(contracts.map((contract) => contract.surface)).size;
  return (
    <section className="rounded-lg border border-border bg-background-alt px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-foreground">{domain}</span>
        <Badge tone="neutral">
          {surfaces} {surfaces === 1 ? 'surface' : 'surfaces'}
        </Badge>
        {site ? <Badge tone="info">Version {site.current_version}</Badge> : null}
      </div>
      <p className="mt-2 text-xs text-muted">
        Manual choices apply to every current and future URL on this domain and surface.
      </p>
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
        title="No extraction preferences yet"
        description="Source choices appear after a crawl observes usable field candidates or an operator activates a grounded correction."
        className="p-0"
      />
    );
  }
  const grouped = groupContractsByTemplate(contracts);
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Field defaults</h3>
        <p className="mt-1 text-xs text-muted">
          One reusable source choice per field. AI suggestions remain inactive until promoted.
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
              <CheckCircle2 className="size-3.5" /> Saved for this surface
            </span>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          <span>{contract.success_count} accepted observations</span>
          <span>{contract.rejection_count} rejected observations</span>
          {isProposed && selected ? (
            <Button
              type="button"
              variant="neutral"
              size="sm"
              disabled={pending}
              onClick={() => onSelectSource(contract, selected.value)}
            >
              Use as domain default
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

// --- helpers ---------------------------------------------------------------

function originDescriptor(origin: string): OriginDescriptor {
  if (origin === 'operator') return { label: 'Manual default', tone: 'accent' };
  if (origin === 'llm_proposed') return { label: 'AI suggested', tone: 'info' };
  return { label: 'Automatic', tone: 'neutral' };
}

function groupContractsByTemplate(contracts: KnowledgeContract[]) {
  const groups = new Map<string, Map<string, KnowledgeContract[]>>();
  for (const contract of contracts) {
    const fields = groups.get(contract.surface) ?? new Map<string, KnowledgeContract[]>();
    const rows = fields.get(contract.canonical_field) ?? [];
    rows.push(contract);
    fields.set(contract.canonical_field, rows);
    groups.set(contract.surface, fields);
  }

  return Array.from(groups.entries()).map(
    ([surface, fields]) =>
      [
        surface,
        Array.from(fields.values())
          .map((rows) => {
            const preferred = rows[0];
            return {
              ...preferred,
              candidates: mergeContractRows(rows, 'candidates'),
              latest_values: mergeContractRows(rows, 'latest_values'),
              success_count: rows.reduce((total, row) => total + row.success_count, 0),
              rejection_count: rows.reduce((total, row) => total + row.rejection_count, 0),
            };
          })
          .sort((left, right) => left.canonical_field.localeCompare(right.canonical_field)),
      ] as const,
  );
}

function mergeContractRows(
  rows: KnowledgeContract[],
  key: 'candidates' | 'latest_values',
): Array<Record<string, unknown>> {
  const merged = new Map<string, Record<string, unknown>>();
  for (const row of rows) {
    for (const item of row[key]) {
      const source = String(item.source ?? '').trim();
      if (!source) continue;
      if (!merged.has(source)) merged.set(source, item);
    }
  }
  return Array.from(merged.values());
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
