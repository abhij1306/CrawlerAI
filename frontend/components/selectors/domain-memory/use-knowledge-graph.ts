import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../../lib/api';
import type {
  KnowledgeContract,
  KnowledgeGraphResponse,
  KnowledgeSiteRecord,
} from '../../../lib/api/types';
import type { DomainWorkspace } from './types';

export type KnowledgeGraphData = {
  graph: KnowledgeGraphResponse;
  site: KnowledgeSiteRecord | null;
  contracts: KnowledgeContract[];
};

type SelectSourceVariables = {
  contract: KnowledgeContract;
  selectedSource: string;
  expectedVersion: number | null;
};

// Single orchestrated fetch keyed by domain: the bounded graph, the site record,
// and every page_template's source contracts. Contracts depend on the graph's
// template nodes, so they are resolved inside one queryFn rather than fanned out
// across N dynamic hooks.
export function useKnowledgeGraph(workspace: DomainWorkspace) {
  const queryClient = useQueryClient();
  const domain = workspace.domain;

  const query = useQuery<KnowledgeGraphData>({
    queryKey: queryKeys.knowledgeGraph.domain(domain),
    queryFn: async () => {
      const [graph, siteResponse] = await Promise.all([
        api.getKnowledgeGraph({ domain, depth: 2, limit: 200 }),
        api.listKnowledgeSites().catch(() => null),
      ]);
      const templateIds = graph.nodes
        .filter((node) => node.entity_type === 'page_template')
        .map((node) => node.id);
      const contractResponses = await Promise.all(
        templateIds.map((templateId) => api.listKnowledgeContracts(templateId)),
      );
      const site =
        siteResponse?.sites.find((entry) => entry.domain === domain) ??
        workspace.knowledgeSite ??
        null;
      return {
        graph,
        site,
        contracts: contractResponses.flatMap((response) => response.contracts),
      };
    },
    enabled: Boolean(domain),
    staleTime: 30_000,
  });

  const selectSource = useMutation({
    mutationFn: ({ contract, selectedSource, expectedVersion }: SelectSourceVariables) =>
      api.selectKnowledgeContractSource(contract.id, {
        selected_source: selectedSource,
        expected_version: expectedVersion,
        template_id: contract.template_id,
        surface: contract.surface,
        canonical_field: contract.canonical_field,
      }),
    onSuccess: (response, { contract }) => {
      queryClient.setQueryData<KnowledgeGraphData>(
        queryKeys.knowledgeGraph.domain(domain),
        (previous) =>
          previous
            ? {
                ...previous,
                contracts: previous.contracts.map((entry) =>
                  entry.id === contract.id ? response.contract : entry,
                ),
              }
            : previous,
      );
    },
  });

  return { query, selectSource };
}
