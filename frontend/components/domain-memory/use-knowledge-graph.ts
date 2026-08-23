import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { knowledgeApi } from '@lib/api/knowledge';
import type { KnowledgeContract, KnowledgeSiteRecord } from '@lib/api/knowledge';
import type { DomainWorkspace } from './types';

type KnowledgeGraphData = {
  site: KnowledgeSiteRecord | null;
  contracts: KnowledgeContract[];
};

type SelectSourceVariables = {
  contract: KnowledgeContract;
  selectedSource: string;
  expectedVersion: number | null;
};

// One domain-scoped request returns all observed contracts. The UI folds the
// per-template provenance rows into one preference per surface and field.
export function useKnowledgeGraph(workspace: DomainWorkspace) {
  const queryClient = useQueryClient();
  const domain = workspace.domain;

  const query = useQuery<KnowledgeGraphData>({
    queryKey: queryKeys.knowledgeGraph.domain(domain),
    queryFn: async () => {
      const [contractsResponse, siteResponse] = await Promise.all([
        knowledgeApi.listKnowledgeContractsByDomain(domain),
        knowledgeApi.listKnowledgeSites().catch(() => null),
      ]);
      const site =
        siteResponse?.sites.find((entry) => entry.domain === domain) ??
        workspace.knowledgeSite ??
        null;
      return { site, contracts: contractsResponse.contracts };
    },
    enabled: Boolean(domain),
    staleTime: 30_000,
  });

  const selectSource = useMutation({
    mutationFn: ({ contract, selectedSource, expectedVersion }: SelectSourceVariables) =>
      knowledgeApi.selectKnowledgeContractSource(contract.id, {
        selected_source: selectedSource,
        expected_version: expectedVersion,
        template_id: contract.template_id,
        surface: contract.surface,
        canonical_field: contract.canonical_field,
      }),
    onSuccess: (response, { contract, selectedSource }) => {
      queryClient.setQueryData<KnowledgeGraphData>(
        queryKeys.knowledgeGraph.domain(domain),
        (previous) =>
          previous
            ? {
                ...previous,
                contracts: previous.contracts.map((entry) =>
                  entry.surface === contract.surface &&
                  entry.canonical_field === contract.canonical_field
                    ? {
                        ...entry,
                        selected_source: selectedSource,
                        selection_origin: 'operator',
                        selection_history:
                          entry.id === response.contract.id
                            ? response.contract.selection_history
                            : entry.selection_history,
                      }
                    : entry,
                ),
              }
            : previous,
      );
    },
  });

  return { query, selectSource };
}
