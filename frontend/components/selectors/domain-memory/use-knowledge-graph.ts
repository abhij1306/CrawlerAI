import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../../lib/api';
import type {
  ExtractionProfile,
  ExtractionProfilePayload,
  KnowledgeContract,
  KnowledgeSiteRecord,
} from '../../../lib/api/types';
import type { DomainWorkspace } from './types';

type KnowledgeGraphData = {
  site: KnowledgeSiteRecord | null;
  contracts: KnowledgeContract[];
  profiles: Record<string, ExtractionProfile>;
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
        api.listKnowledgeContractsByDomain(domain),
        api.listKnowledgeSites().catch(() => null),
      ]);
      const site =
        siteResponse?.sites.find((entry) => entry.domain === domain) ??
        workspace.knowledgeSite ??
        null;
      const surfaces = Array.from(
        new Set([
          ...workspace.surfaces.map((surface) => surface.surface),
          ...contractsResponse.contracts.map((contract) => contract.surface),
        ]),
      ).filter(Boolean);
      const profileRows = await Promise.all(
        surfaces.map((surface) => api.getExtractionProfile(domain, surface).catch(() => null)),
      );
      const profiles = Object.fromEntries(
        profileRows
          .filter((profile): profile is ExtractionProfile => Boolean(profile))
          .map((profile) => [profile.surface, profile]),
      );
      return { site, contracts: contractsResponse.contracts, profiles };
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

  const saveProfile = useMutation({
    mutationFn: (payload: ExtractionProfilePayload) => api.saveExtractionProfile(payload),
    onSuccess: (profile) => {
      queryClient.setQueryData<KnowledgeGraphData>(
        queryKeys.knowledgeGraph.domain(domain),
        (previous) =>
          previous
            ? {
                ...previous,
                profiles: { ...previous.profiles, [profile.surface]: profile },
              }
            : previous,
      );
    },
  });

  return { query, selectSource, saveProfile };
}
