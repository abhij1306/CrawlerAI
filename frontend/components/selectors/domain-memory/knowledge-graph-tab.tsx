import { CheckCircle2, GitBranch, RefreshCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api } from '../../../lib/api';
import type {
  KnowledgeContract,
  KnowledgeEntity,
  KnowledgeGraphResponse,
  KnowledgeRelationship,
  KnowledgeSiteRecord,
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
import { knowledgeFieldLabel, knowledgeSourceOptions, surfaceLabel, titleCaseToken } from './utils';

type KnowledgeGraphTabProps = {
  selectedWorkspace: DomainWorkspace;
};

type GraphState = {
  graph: KnowledgeGraphResponse | null;
  site: KnowledgeSiteRecord | null;
  contracts: KnowledgeContract[];
  loading: boolean;
  error: string;
  updatingContractId: string;
  savedContractId: string;
};

const INITIAL_STATE: GraphState = {
  graph: null,
  site: null,
  contracts: [],
  loading: false,
  error: '',
  updatingContractId: '',
  savedContractId: '',
};

export function KnowledgeGraphTab({ selectedWorkspace }: KnowledgeGraphTabProps) {
  const [state, setState] = useState<GraphState>(INITIAL_STATE);
  const requestIdRef = useRef(0);
  const currentSite = latestKnowledgeSite(
    state.site,
    selectedWorkspace.knowledgeSite,
    selectedWorkspace.domain,
  );
  const graphVersion = currentSite?.current_version ?? null;

  const loadGraph = useCallback(async () => {
    const requestId = (requestIdRef.current += 1);
    setState((current) => ({ ...current, loading: true, error: '' }));
    try {
      const [graph, siteResponse] = await Promise.all([
        api.getKnowledgeGraph({
          domain: selectedWorkspace.domain,
          depth: 2,
          limit: 200,
        }),
        api.listKnowledgeSites().catch(() => null),
      ]);
      const templateIds = graph.nodes
        .filter((node) => node.entity_type === 'page_template')
        .map((node) => node.id);
      const contractResponses = await Promise.all(
        templateIds.map((templateId) => api.listKnowledgeContracts(templateId)),
      );
      if (requestId !== requestIdRef.current) return;
      setState({
        graph,
        site:
          siteResponse?.sites.find((site) => site.domain === selectedWorkspace.domain) ??
          selectedWorkspace.knowledgeSite ??
          null,
        contracts: contractResponses.flatMap((response) => response.contracts),
        loading: false,
        error: '',
        updatingContractId: '',
        savedContractId: '',
      });
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setState((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : 'Unable to load Knowledge Graph.',
      }));
    }
  }, [selectedWorkspace.domain, selectedWorkspace.knowledgeSite]);

  useEffect(() => {
    void loadGraph();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadGraph]);

  const nodeCounts = useMemo(() => countByType(state.graph?.nodes ?? []), [state.graph?.nodes]);
  const templatesById = useMemo(() => {
    const entries = new Map<string, KnowledgeEntity>();
    for (const node of state.graph?.nodes ?? []) {
      if (node.entity_type === 'page_template') entries.set(node.id, node);
    }
    return entries;
  }, [state.graph?.nodes]);

  async function selectSource(contract: KnowledgeContract, selectedSource: string) {
    if (!selectedSource || selectedSource === contract.selected_source) return;
    setState((current) => ({
      ...current,
      updatingContractId: contract.id,
      savedContractId: '',
      error: '',
    }));
    try {
      const response = await api.selectKnowledgeContractSource(contract.id, {
        selected_source: selectedSource,
        expected_version: graphVersion,
        template_id: contract.template_id,
        surface: contract.surface,
        canonical_field: contract.canonical_field,
      });
      setState((current) => ({
        ...current,
        contracts: current.contracts.map((entry) =>
          entry.id === contract.id ? response.contract : entry,
        ),
        updatingContractId: '',
        savedContractId: contract.id,
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        updatingContractId: '',
        savedContractId: '',
        error: error instanceof Error ? error.message : 'Unable to update source selection.',
      }));
    }
  }

  return (
    <SurfaceSection
      title="Knowledge Graph"
      description="Bounded site graph, canonical entities, source contracts, and operator selections."
      icon={GitBranch}
      action={
        <Button
          type="button"
          variant="neutral"
          size="sm"
          onClick={() => void loadGraph()}
          disabled={state.loading}
        >
          <RefreshCcw className="size-3" />
          {state.loading ? 'Refreshing...' : 'Refresh'}
        </Button>
      }
      bodyClassName="space-y-5"
    >
      {state.error ? <DataRegionError message={state.error} className="p-0" /> : null}
      {state.loading && !state.graph ? (
        <DataRegionLoading count={6} className="p-0" />
      ) : state.graph && state.graph.nodes.length ? (
        <>
          <GraphSummary site={currentSite} graph={state.graph} nodeCounts={nodeCounts} />
          <ContractPanel
            contracts={state.contracts}
            templatesById={templatesById}
            updatingContractId={state.updatingContractId}
            savedContractId={state.savedContractId}
            onSelectSource={selectSource}
          />
          <GraphVisual nodes={state.graph.nodes} relationships={state.graph.relationships} />
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
  nodeCounts,
}: {
  site: KnowledgeSiteRecord | null;
  graph: KnowledgeGraphResponse;
  nodeCounts: Map<string, number>;
}) {
  const metrics = [
    { label: 'Version', value: site?.current_version ?? '0' },
    { label: 'Status', value: titleCaseToken(site?.projection_status ?? 'unknown') },
    { label: 'Nodes', value: graph.nodes.length },
    { label: 'Edges', value: graph.relationships.length },
    ...Array.from(nodeCounts.entries()).map(([type, count]) => ({
      label: titleCaseToken(type),
      value: count,
    })),
  ];
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {metrics.map((metric) => (
        <KVTile key={metric.label} label={metric.label} value={metric.value} />
      ))}
    </div>
  );
}

function GraphVisual({
  nodes,
  relationships,
}: {
  nodes: KnowledgeEntity[];
  relationships: KnowledgeRelationship[];
}) {
  const nodeById = new Map(nodes.map((node) => [node.id, node] as const));
  const visibleNodes = nodes.slice(0, 12);
  const visibleRelationships = relationships.slice(0, 12);
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Site model</h3>
        <p className="mt-1 text-xs text-muted">
          {nodes.length} entities · {relationships.length} relationships
        </p>
      </div>
      <div className="grid overflow-hidden rounded-lg border border-border lg:grid-cols-2 lg:divide-x lg:divide-border">
        <div className="divide-y divide-border">
          {visibleNodes.map((node) => (
            <div key={node.id} className="flex min-w-0 items-center gap-3 px-4 py-3">
              <Badge tone={badgeTone(node.entity_type)}>{titleCaseToken(node.entity_type)}</Badge>
              <span className="min-w-0 truncate text-sm text-foreground">{nodeLabel(node)}</span>
            </div>
          ))}
        </div>
        <div className="divide-y divide-border">
          {visibleRelationships.length ? (
            visibleRelationships.map((relationship) => (
              <div key={relationship.id} className="px-4 py-3">
                <div className="text-xs font-medium text-foreground">
                  {titleCaseToken(relationship.relationship_type.toLowerCase())}
                </div>
                <div className="mt-1 truncate text-xs text-muted">
                  {nodeLabel(nodeById.get(relationship.source_entity_id))} →{' '}
                  {nodeLabel(nodeById.get(relationship.target_entity_id))}
                </div>
              </div>
            ))
          ) : (
            <div className="px-4 py-6 text-xs text-muted">No relationships</div>
          )}
        </div>
      </div>
    </section>
  );
}

function ContractPanel({
  contracts,
  templatesById,
  updatingContractId,
  savedContractId,
  onSelectSource,
}: {
  contracts: KnowledgeContract[];
  templatesById: Map<string, KnowledgeEntity>;
  updatingContractId: string;
  savedContractId: string;
  onSelectSource: (contract: KnowledgeContract, selectedSource: string) => Promise<void>;
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
        <p className="mt-1 text-xs text-muted">Preferred source for future matching runs</p>
      </div>
      {grouped.map(([templateId, templateContracts]) => {
        const template = templatesById.get(templateId);
        return (
          <section key={templateId} className="overflow-hidden rounded-lg border border-border">
            <header className="flex flex-wrap items-center justify-between gap-3 bg-background-alt px-4 py-3">
              <div className="min-w-0">
                <div className="text-xs font-medium text-foreground">
                  {surfaceLabel(templateContracts[0].surface)}
                </div>
                <div className="mt-1 truncate font-mono text-xs text-muted">
                  {templateRoute(template)}
                </div>
              </div>
              <Badge tone="neutral">{templateContracts.length} fields</Badge>
            </header>
            <div className="divide-y divide-border">
              {templateContracts.map((contract) => (
                <ContractPreferenceRow
                  key={contract.id}
                  contract={contract}
                  updating={updatingContractId === contract.id}
                  saved={savedContractId === contract.id}
                  onSelectSource={onSelectSource}
                />
              ))}
            </div>
          </section>
        );
      })}
    </section>
  );
}

function ContractPreferenceRow({
  contract,
  updating,
  saved,
  onSelectSource,
}: {
  contract: KnowledgeContract;
  updating: boolean;
  saved: boolean;
  onSelectSource: (contract: KnowledgeContract, selectedSource: string) => Promise<void>;
}) {
  const field = knowledgeFieldLabel(contract.canonical_field);
  const sourceOptions = knowledgeSourceOptions(contract);
  const selected =
    sourceOptions.find((option) => option.value === contract.selected_source) ?? sourceOptions[0];
  return (
    <div className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{field.label}</span>
          <Badge tone="neutral">{field.group}</Badge>
          <Badge tone={contract.selection_origin === 'operator' ? 'accent' : 'info'}>
            {contract.selection_origin === 'operator' ? 'Manual' : 'Automatic'}
          </Badge>
          {saved ? (
            <span className="flex items-center gap-1 text-xs font-medium text-success">
              <CheckCircle2 className="size-3.5" /> Saved
            </span>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          <span>{contract.success_count ? 'Observed' : 'Not observed'}</span>
          <span>{contract.rejection_count} rejected observations</span>
          <span>Fallback enabled</span>
        </div>
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 text-xs font-medium text-secondary">Preferred source</div>
        {sourceOptions.length > 1 && selected ? (
          <Dropdown<string>
            value={selected.value}
            onChange={(value) => void onSelectSource(contract, value)}
            options={sourceOptions.map((source) => ({ value: source.value, label: source.label }))}
            ariaLabel={`Source for ${contract.canonical_field}`}
            disabled={updating}
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

function countByType(nodes: KnowledgeEntity[]) {
  const counts = new Map<string, number>();
  for (const node of nodes) {
    counts.set(node.entity_type, (counts.get(node.entity_type) ?? 0) + 1);
  }
  return counts;
}

function nodeLabel(node: KnowledgeEntity | undefined) {
  if (!node) return 'unknown';
  if (node.entity_type === 'page_template') return templateRoute(node);
  if (node.entity_type === 'route_pattern')
    return String(node.properties.pattern ?? 'Page pattern');
  if (node.entity_type === 'page') {
    try {
      return new URL(node.canonical_key).pathname;
    } catch {
      return 'Page';
    }
  }
  return node.canonical_name || titleCaseToken(node.entity_type);
}

function templateRoute(node: KnowledgeEntity | undefined) {
  return String(node?.properties.route_pattern ?? '').trim() || 'Page pattern unavailable';
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

function badgeTone(type: string): 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info' {
  if (type === 'product') return 'success';
  if (type === 'page_template') return 'accent';
  if (type === 'offer') return 'warning';
  if (type === 'brand') return 'info';
  return 'neutral';
}

function latestKnowledgeSite(
  stateSite: KnowledgeSiteRecord | null,
  workspaceSite: KnowledgeSiteRecord | null,
  domain: string,
) {
  const scopedStateSite = stateSite?.domain === domain ? stateSite : null;
  const scopedWorkspaceSite = workspaceSite?.domain === domain ? workspaceSite : null;
  if (!scopedStateSite) return scopedWorkspaceSite ?? null;
  if (!scopedWorkspaceSite) return scopedStateSite;
  return scopedWorkspaceSite.current_version > scopedStateSite.current_version
    ? scopedWorkspaceSite
    : scopedStateSite;
}
