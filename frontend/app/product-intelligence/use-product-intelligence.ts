import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useCallback, useMemo, useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import type { HistoryItem } from '../../components/ui/history-drawer';
import { api } from '../../lib/api';
import type { ProductIntelligenceDiscoveryResponse } from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { searchProviderLabel } from './product-intelligence-utils';
import {
  DEFAULT_OPTIONS,
  candidateConfidence,
  detailOptions,
  detailToDiscovery,
  loadPrefillPayload,
  parseDomainLines,
  searchProvider,
} from './product-intelligence-utils';

export function useProductIntelligence() {
  const navigate = useNavigate();
  const [initialPrefill] = useState(loadPrefillPayload);
  const prefill = initialPrefill.payload;
  const [options, setOptions] = useState(DEFAULT_OPTIONS);
  const [allowedDomainsText, setAllowedDomainsText] = useState('');
  const [excludedDomainsText, setExcludedDomainsText] = useState('');
  const [discoveryOverride, setDiscoveryOverride] =
    useState<ProductIntelligenceDiscoveryResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(initialPrefill.error);
  const [selectedUrls, setSelectedUrls] = useState<string[]>([]);
  const [jsonModalCandidate, setJsonModalCandidate] = useState<
    ProductIntelligenceDiscoveryResponse['candidates'][number] | null
  >(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [optionsEdited, setOptionsEdited] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [confidenceFilter, setConfidenceFilter] = useState<'all' | 'high' | 'medium' | 'low'>(
    'all',
  );
  const {
    data: jobsData,
    isLoading: jobsLoading,
    refetch: refetchJobs,
  } = useQuery({
    queryKey: queryKeys.productIntelligence.jobs(),
    queryFn: () => api.listProductIntelligenceJobs({ limit: 20 }),
  });
  const sourceRecords = useMemo(() => prefill.records ?? [], [prefill.records]);
  const defaultJobId = sourceRecords.length ? null : (jobsData?.[0]?.id ?? null);
  const resolvedActiveJobId = activeJobId ?? defaultJobId;
  const {
    data: detailData,
    isLoading: detailLoading,
    isFetching: detailFetching,
  } = useQuery({
    queryKey: queryKeys.productIntelligence.detail(resolvedActiveJobId ?? 0),
    queryFn: () => api.getProductIntelligenceJob(resolvedActiveJobId ?? 0),
    enabled: resolvedActiveJobId !== null,
  });
  const historyItems: HistoryItem[] = useMemo(
    () =>
      (jobsData ?? []).map((job) => ({
        id: job.id,
        status: job.status,
        created_at: job.created_at,
        label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
        meta: `${Number(job.summary?.candidate_count ?? 0)} URLs found`,
      })),
    [jobsData],
  );
  const detailHydratedOptions = useMemo(
    () => (detailData ? detailOptions(detailData.job.options) : DEFAULT_OPTIONS),
    [detailData],
  );
  const detailDiscovery = useMemo(
    () => (detailData ? detailToDiscovery(detailData) : null),
    [detailData],
  );
  const discovery = discoveryOverride ?? detailDiscovery;
  const effectiveOptions = optionsEdited || !detailData ? options : detailHydratedOptions;
  const effectiveAllowedDomainsText = optionsEdited
    ? allowedDomainsText
    : detailHydratedOptions.allowed_domains.join('\n');
  const effectiveExcludedDomainsText = optionsEdited
    ? excludedDomainsText
    : detailHydratedOptions.excluded_domains.join('\n');
  const visibleSourceRecords = useMemo(
    () =>
      sourceRecords.length
        ? sourceRecords
        : detailData
          ? detailData.source_products.map((source) => ({
              id: source.source_record_id,
              run_id: source.source_run_id,
              source_url: source.source_url,
              data: source.payload,
            }))
          : [],
    [detailData, sourceRecords],
  );
  const activeSourceRunId = sourceRecords.length
    ? (prefill.source_run_id ??
      sourceRecords.find((record) => typeof record.run_id === 'number')?.run_id ??
      null)
    : (detailData?.job.source_run_id ??
      visibleSourceRecords.find((record) => typeof record.run_id === 'number')?.run_id ??
      prefill.source_run_id ??
      null);
  const uniqueSelectedUrls = useMemo(
    () =>
      Array.from(new Set(selectedUrls)).filter((url) =>
        (discovery?.candidates ?? []).some((candidate) => candidate.url === url),
      ),
    [discovery, selectedUrls],
  );
  const selectedUrlSet = useMemo(() => new Set(uniqueSelectedUrls), [uniqueSelectedUrls]);
  const filteredCandidates = useMemo(() => {
    const all = discovery?.candidates ?? [];
    return all.filter((candidate) => candidateVisible(candidate, searchText, confidenceFilter));
  }, [discovery, searchText, confidenceFilter]);
  const groupedCandidates = useMemo(() => {
    const groups = new Map<number, typeof filteredCandidates>();
    filteredCandidates.forEach((candidate) => {
      const index = candidate.source_index ?? 0;
      if (!groups.has(index)) groups.set(index, []);
      groups.get(index)!.push(candidate);
    });
    return Array.from(groups.entries()).map(([sourceIndex, candidates]) => ({
      sourceIndex,
      sourceTitle: candidates[0].source_title,
      sourceBrand: candidates[0].source_brand,
      sourcePrice: candidates[0].source_price,
      sourceCurrency: candidates[0].source_currency,
      sourceUrl: candidates[0].source_url,
      candidates,
    }));
  }, [filteredCandidates]);
  const confidenceDistribution = useMemo(() => {
    const all = discovery?.candidates ?? [];
    return {
      high: all.filter((candidate) => candidateConfidence(candidate) >= 0.6).length,
      medium: all.filter((candidate) => {
        const score = candidateConfidence(candidate);
        return score >= 0.4 && score < 0.6;
      }).length,
      low: all.filter((candidate) => candidateConfidence(candidate) < 0.4).length,
    };
  }, [discovery]);
  const selectedDomainSummary = useMemo(() => {
    if (!uniqueSelectedUrls.length) return null;
    const selectedUrlSet = new Set(uniqueSelectedUrls);
    const domains = Array.from(
      (discovery?.candidates ?? []).reduce<Set<string>>((acc, candidate) => {
        if (selectedUrlSet.has(candidate.url) && candidate.domain) {
          acc.add(candidate.domain);
        }
        return acc;
      }, new Set<string>()),
    );
    return { count: uniqueSelectedUrls.length, domains };
  }, [discovery, uniqueSelectedUrls]);
  const discover = useCallback(
    async function discover() {
      if (!visibleSourceRecords.length) return;
      setPending(true);
      setError('');
      setDiscoveryOverride(null);
      setSelectedUrls([]);
      try {
        const sourceRecordIds = visibleSourceRecords
          .map((record) => record.id)
          .filter((value): value is number => typeof value === 'number');
        const canUseRecordIds = sourceRecordIds.length === visibleSourceRecords.length;
        const submittedOptions = {
          ...effectiveOptions,
          search_provider: searchProvider(effectiveOptions.search_provider),
          allowed_domains: parseDomainLines(effectiveAllowedDomainsText),
          excluded_domains: parseDomainLines(effectiveExcludedDomainsText),
        };
        const response = await api.discoverProductIntelligence({
          source_run_id: activeSourceRunId,
          source_record_ids: canUseRecordIds ? sourceRecordIds : [],
          source_records: canUseRecordIds ? [] : visibleSourceRecords,
          options: submittedOptions,
        });
        const echoedProvider = searchProvider(
          response.search_provider ?? response.options?.search_provider,
        );
        if (echoedProvider !== submittedOptions.search_provider) {
          setError(
            `Provider mismatch: submitted ${searchProviderLabel(submittedOptions.search_provider)}, backend used ${searchProviderLabel(echoedProvider)}.`,
          );
        }
        setDiscoveryOverride(response);
        setActiveJobId(response.job_id);
        const nextOptions = detailOptions(response.options);
        setOptions(nextOptions);
        setAllowedDomainsText(nextOptions.allowed_domains.join('\n'));
        setExcludedDomainsText(nextOptions.excluded_domains.join('\n'));
        setOptionsEdited(false);
        await refetchJobs();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'Unable to discover candidates.');
      } finally {
        setPending(false);
      }
    },
    [
      activeSourceRunId,
      effectiveAllowedDomainsText,
      effectiveExcludedDomainsText,
      effectiveOptions,
      refetchJobs,
      visibleSourceRecords,
    ],
  );

  const toggleUrl = useCallback(function toggleUrl(url: string) {
    setSelectedUrls((current) =>
      current.includes(url) ? current.filter((item) => item !== url) : [...current, url],
    );
  }, []);

  const sendSelectedToBatchCrawl = useCallback(
    function sendSelectedToBatchCrawl() {
      if (!uniqueSelectedUrls.length) return;
      window.sessionStorage.setItem(
        STORAGE_KEYS.BULK_PREFILL,
        JSON.stringify({ domain: 'commerce', urls: uniqueSelectedUrls }),
      );
      navigate('/crawl?module=pdp&mode=batch', { replace: true });
    },
    [navigate, uniqueSelectedUrls],
  );

  const toggleAllUrls = useCallback(
    function toggleAllUrls() {
      const filteredUrls = filteredCandidates.flatMap((candidate) =>
        candidate.url ? [candidate.url] : [],
      );
      const selectedUrlSet = new Set(selectedUrls);
      const allFilteredSelected = filteredUrls.every((url) => selectedUrlSet.has(url));
      if (allFilteredSelected && filteredUrls.length > 0) {
        const filteredUrlSet = new Set(filteredUrls);
        setSelectedUrls((current) => current.filter((url) => !filteredUrlSet.has(url)));
      } else {
        setSelectedUrls((current) => Array.from(new Set([...current, ...filteredUrls])));
      }
    },
    [filteredCandidates, selectedUrls],
  );

  const openJob = useCallback(function openJob(jobId: number) {
    setActiveJobId(jobId);
    setDiscoveryOverride(null);
    setSelectedUrls([]);
    setOptionsEdited(false);
  }, []);

  const resolvingLatestJob =
    !sourceRecords.length && !discoveryOverride && !jobsData && jobsLoading;
  const resolvingDetail =
    resolvedActiveJobId !== null &&
    !discoveryOverride &&
    !detailData &&
    (detailLoading || detailFetching);
  const loadingDiscovery = pending || resolvingLatestJob || resolvingDetail;

  return {
    confidenceDistribution,
    confidenceFilter,
    configOpen,
    discover,
    discovery,
    effectiveAllowedDomainsText,
    effectiveExcludedDomainsText,
    effectiveOptions,
    error,
    filteredCandidates,
    groupedCandidates,
    historyItems,
    historyOpen,
    jsonModalCandidate,
    loadingDiscovery,
    openJob,
    pending,
    resolvedActiveJobId,
    searchText,
    selectedDomainSummary,
    selectedUrls,
    selectedUrlSet,
    sendSelectedToBatchCrawl,
    setAllowedDomainsText,
    setConfigOpen,
    setConfidenceFilter,
    setExcludedDomainsText,
    setHistoryOpen,
    setJsonModalCandidate,
    setOptions,
    setOptionsEdited,
    setSearchText,
    setSelectedUrls,
    toggleAllUrls,
    toggleUrl,
    uniqueSelectedUrls,
    visibleSourceRecords,
  };
}

export type ProductIntelligenceController = ReturnType<typeof useProductIntelligence>;

function candidateVisible(
  candidate: ProductIntelligenceDiscoveryResponse['candidates'][number],
  searchText: string,
  confidenceFilter: 'all' | 'high' | 'medium' | 'low',
) {
  if (searchText) {
    const query = searchText.toLowerCase();
    const matchesSearch =
      (candidate.source_title ?? '').toLowerCase().includes(query) ||
      (candidate.source_brand ?? '').toLowerCase().includes(query) ||
      (candidate.domain ?? '').toLowerCase().includes(query) ||
      (candidate.url ?? '').toLowerCase().includes(query);
    if (!matchesSearch) return false;
  }
  if (confidenceFilter === 'all') return true;
  const score = candidateConfidence(candidate);
  if (confidenceFilter === 'high') return score >= 0.6;
  if (confidenceFilter === 'medium') return score >= 0.4 && score < 0.6;
  return score < 0.4;
}
