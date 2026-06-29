import { GitBranch, RefreshCcw } from 'lucide-react';
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
  DetailRow,
  KVTile,
  SurfaceSection,
} from '../../ui/patterns';
import { Badge, Button, Dropdown } from '../../ui/primitives';
import type { DomainWorkspace } from './types';
import { surfaceLabel, titleCaseToken } from './utils';

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
};

const INITIAL_STATE: GraphState = {
  graph: null,
  site: null,
  contracts: [],
  loading: false,
  error: '',
  updatingContractId: '',
};

export function KnowledgeGraphTab({ selectedWorkspace }: KnowledgeGraphTabProps) {
  const [state, setState] = useState<GraphState>(INITIAL_STATE);
  const requestIdRef = useRef(0);
  const currentSite = state.site ?? selectedWorkspace.knowledgeSite ?? null;
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
    setState((current) => ({ ...current, updatingContractId: contract.id, error: '' }));
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
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        updatingContractId: '',
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
          <GraphVisual nodes={state.graph.nodes} relationships={state.graph.relationships} />
          <ContractPanel
            contracts={state.contracts}
            templatesById={templatesById}
            updatingContractId={state.updatingContractId}
            onSelectSource={selectSource}
          />
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
  return (
    <div className="grid gap-3 md:grid-cols-4">
      <KVTile label="Version" value={site?.current_version ?? '0'} />
      <KVTile label="Status" value={titleCaseToken(site?.projection_status ?? 'unknown')} />
      <KVTile label="Nodes" value={graph.nodes.length} />
      <KVTile label="Edges" value={graph.relationships.length} />
      {Array.from(nodeCounts.entries()).map(([type, count]) => (
        <KVTile key={type} label={titleCaseToken(type)} value={count} />
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
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.6fr)]">
      <div className="grid gap-3 md:grid-cols-2">
        {nodes.map((node) => (
          <DetailRow key={node.id}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={badgeTone(node.entity_type)}>{titleCaseToken(node.entity_type)}</Badge>
              <span className="min-w-0 truncate text-sm font-medium text-foreground">
                {node.canonical_name || node.canonical_key}
              </span>
            </div>
            <code className="mt-2 block text-xs break-all text-secondary">
              {node.canonical_key}
            </code>
          </DetailRow>
        ))}
      </div>
      <div className="space-y-2">
        {relationships.length ? (
          relationships.map((relationship) => (
            <DetailRow key={relationship.id} className="px-4 py-3">
              <div className="type-micro-label">{relationship.relationship_type}</div>
              <div className="mt-2 text-xs text-secondary">
                {nodeLabel(nodeById.get(relationship.source_entity_id))} -&gt;{' '}
                {nodeLabel(nodeById.get(relationship.target_entity_id))}
              </div>
            </DetailRow>
          ))
        ) : (
          <DataRegionEmpty
            title="No relationships"
            description="Nodes exist, but no bounded edges were returned."
            className="p-0"
          />
        )}
      </div>
    </div>
  );
}

function ContractPanel({
  contracts,
  templatesById,
  updatingContractId,
  onSelectSource,
}: {
  contracts: KnowledgeContract[];
  templatesById: Map<string, KnowledgeEntity>;
  updatingContractId: string;
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
  return (
    <div className="space-y-3">
      {contracts.map((contract) => {
        const sourceOptions = candidateSources(contract);
        return (
          <DetailRow key={contract.id}>
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-foreground">{contract.canonical_field}</span>
                  <Badge tone={contract.selection_origin === 'operator' ? 'accent' : 'info'}>
                    {titleCaseToken(contract.selection_origin)}
                  </Badge>
                  <span className="text-xs text-muted">{surfaceLabel(contract.surface)}</span>
                </div>
                <div className="mt-2 text-xs text-secondary">
                  {templateLabel(templatesById.get(contract.template_id))}
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted">
                  <span>{contract.success_count} hits</span>
                  <span>{contract.rejection_count} rejects</span>
                  <span>{sourceOptions.length} candidates</span>
                </div>
              </div>
              <Dropdown<string>
                value={contract.selected_source}
                onChange={(value) => void onSelectSource(contract, value)}
                options={sourceOptions.map((source) => ({ value: source, label: source }))}
                ariaLabel={`Source for ${contract.canonical_field}`}
                disabled={!sourceOptions.length || updatingContractId === contract.id}
              />
            </div>
          </DetailRow>
        );
      })}
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

function candidateSources(contract: KnowledgeContract) {
  const sources = contract.candidates
    .map((candidate) => String(candidate.source ?? '').trim())
    .filter(Boolean);
  if (contract.selected_source && !sources.includes(contract.selected_source)) {
    sources.unshift(contract.selected_source);
  }
  return sources;
}

function nodeLabel(node: KnowledgeEntity | undefined) {
  if (!node) return 'unknown';
  return node.canonical_name || node.canonical_key;
}

function templateLabel(node: KnowledgeEntity | undefined) {
  if (!node) return 'Template unavailable';
  const route = String(node.properties.route_pattern ?? '').trim();
  return route ? `${node.canonical_key} · ${route}` : node.canonical_key;
}

function badgeTone(type: string): 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info' {
  if (type === 'product') return 'success';
  if (type === 'page_template') return 'accent';
  if (type === 'offer') return 'warning';
  if (type === 'brand') return 'info';
  return 'neutral';
}
