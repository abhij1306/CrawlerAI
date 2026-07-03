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

type DiscoveryCandidate = ProductIntelligenceDiscoveryResponse['candidates'][number];
type SourceRecord = NonNullable<
  ReturnType<typeof loadPrefillPayload>['payload']['records']
>[number];

function historyFromJobs(
  jobs: Awaited<ReturnType<typeof api.listProductIntelligenceJobs>> | undefined,
) {
  return (jobs ?? []).map((job) => ({
    id: job.id,
    status: job.status,
    created_at: job.created_at,
    label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
    meta: `${Number(job.summary?.candidate_count ?? 0)} URLs found`,
  }));
}

function visibleRecords(
  sourceRecords: SourceRecord[],
  detail: Awaited<ReturnType<typeof api.getProductIntelligenceJob>> | undefined,
) {
  if (sourceRecords.length) return sourceRecords;
  return (detail?.source_products ?? []).map((source) => ({
    id: source.source_record_id,
    run_id: source.source_run_id,
    source_url: source.source_url,
    data: source.payload,
  }));
}

function activeSourceRun(
  sourceRecords: SourceRecord[],
  prefillRunId: number | null | undefined,
  detailRunId: number | null | undefined,
  records: SourceRecord[],
) {
  const recordRunId = records.find((record) => typeof record.run_id === 'number')?.run_id ?? null;
  return sourceRecords.length
    ? (prefillRunId ?? recordRunId)
    : (detailRunId ?? recordRunId ?? prefillRunId ?? null);
}

function selectedCandidateUrls(
  selectedUrls: string[],
  discovery: ProductIntelligenceDiscoveryResponse | null,
) {
  const available = new Set((discovery?.candidates ?? []).map((candidate) => candidate.url));
  return Array.from(new Set(selectedUrls)).filter((url) => available.has(url));
}

function groupCandidates(candidates: DiscoveryCandidate[]) {
  const groups = new Map<number, DiscoveryCandidate[]>();
  for (const candidate of candidates) {
    const index = candidate.source_index ?? 0;
    groups.set(index, [...(groups.get(index) ?? []), candidate]);
  }
  return Array.from(groups.entries()).map(([sourceIndex, rows]) => ({
    sourceIndex,
    sourceTitle: rows[0].source_title,
    sourceBrand: rows[0].source_brand,
    sourcePrice: rows[0].source_price,
    sourceCurrency: rows[0].source_currency,
    sourceUrl: rows[0].source_url,
    candidates: rows,
  }));
}

function candidateDistribution(candidates: DiscoveryCandidate[]) {
  const distribution = { high: 0, medium: 0, low: 0 };
  for (const candidate of candidates) {
    const score = candidateConfidence(candidate);
    if (score >= 0.6) distribution.high += 1;
    else if (score >= 0.4) distribution.medium += 1;
    else distribution.low += 1;
  }
  return distribution;
}

function selectedSummary(urls: string[], candidates: DiscoveryCandidate[]) {
  if (!urls.length) return null;
  const selected = new Set(urls);
  const domains = new Set<string>();
  for (const candidate of candidates) {
    if (selected.has(candidate.url) && candidate.domain) domains.add(candidate.domain);
  }
  return { count: urls.length, domains: Array.from(domains) };
}

async function requestDiscovery({
  records,
  sourceRunId,
  options,
  allowedDomainsText,
  excludedDomainsText,
}: {
  records: SourceRecord[];
  sourceRunId: number | null;
  options: typeof DEFAULT_OPTIONS;
  allowedDomainsText: string;
  excludedDomainsText: string;
}) {
  const sourceRecordIds = records
    .map((record) => record.id)
    .filter((value): value is number => typeof value === 'number');
  const canUseRecordIds = sourceRecordIds.length === records.length;
  const submittedOptions = {
    ...options,
    search_provider: searchProvider(options.search_provider),
    allowed_domains: parseDomainLines(allowedDomainsText),
    excluded_domains: parseDomainLines(excludedDomainsText),
  };
  const response = await api.discoverProductIntelligence({
    source_run_id: sourceRunId,
    source_record_ids: canUseRecordIds ? sourceRecordIds : [],
    source_records: canUseRecordIds ? [] : records,
    options: submittedOptions,
  });
  const echoedProvider = searchProvider(
    response.search_provider ?? response.options?.search_provider,
  );
  return {
    response,
    nextOptions: detailOptions(response.options),
    providerError:
      echoedProvider === submittedOptions.search_provider
        ? ''
        : `Provider mismatch: submitted ${searchProviderLabel(submittedOptions.search_provider)}, backend used ${searchProviderLabel(echoedProvider)}.`,
  };
}

function toggleFilteredSelection(current: string[], candidates: DiscoveryCandidate[]) {
  const filteredUrls = candidates.flatMap((candidate) => (candidate.url ? [candidate.url] : []));
  const selected = new Set(current);
  if (filteredUrls.length && filteredUrls.every((url) => selected.has(url))) {
    const filtered = new Set(filteredUrls);
    return current.filter((url) => !filtered.has(url));
  }
  return Array.from(new Set([...current, ...filteredUrls]));
}

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
  const historyItems: HistoryItem[] = useMemo(() => historyFromJobs(jobsData), [jobsData]);
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
    () => visibleRecords(sourceRecords, detailData),
    [detailData, sourceRecords],
  );
  const activeSourceRunId = activeSourceRun(
    sourceRecords,
    prefill.source_run_id,
    detailData?.job.source_run_id,
    visibleSourceRecords,
  );
  const uniqueSelectedUrls = useMemo(
    () => selectedCandidateUrls(selectedUrls, discovery),
    [discovery, selectedUrls],
  );
  const selectedUrlSet = useMemo(() => new Set(uniqueSelectedUrls), [uniqueSelectedUrls]);
  const filteredCandidates = useMemo(() => {
    const all = discovery?.candidates ?? [];
    return all.filter((candidate) => candidateVisible(candidate, searchText, confidenceFilter));
  }, [discovery, searchText, confidenceFilter]);
  const groupedCandidates = useMemo(
    () => groupCandidates(filteredCandidates),
    [filteredCandidates],
  );
  const confidenceDistribution = useMemo(
    () => candidateDistribution(discovery?.candidates ?? []),
    [discovery],
  );
  const selectedDomainSummary = useMemo(
    () => selectedSummary(uniqueSelectedUrls, discovery?.candidates ?? []),
    [discovery, uniqueSelectedUrls],
  );
  const discover = useCallback(
    async function discover() {
      if (!visibleSourceRecords.length) return;
      setPending(true);
      setError('');
      setDiscoveryOverride(null);
      setSelectedUrls([]);
      try {
        const { response, nextOptions, providerError } = await requestDiscovery({
          records: visibleSourceRecords,
          sourceRunId: activeSourceRunId,
          options: effectiveOptions,
          allowedDomainsText: effectiveAllowedDomainsText,
          excludedDomainsText: effectiveExcludedDomainsText,
        });
        setError(providerError);
        setDiscoveryOverride(response);
        setActiveJobId(response.job_id);
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
      setSelectedUrls((current) => toggleFilteredSelection(current, filteredCandidates));
    },
    [filteredCandidates],
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
