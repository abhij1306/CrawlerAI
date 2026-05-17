'use client';

import { useQuery } from '@tanstack/react-query';
import type { Route } from 'next';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import type { HistoryItem } from '../../components/ui/history-drawer';
import { api } from '../../lib/api';
import type { ProductIntelligenceDiscoveryResponse } from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { searchProviderLabel } from './product-intelligence-components';
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
  const router = useRouter();
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
  const jobsQuery = useQuery({
    queryKey: ['product-intelligence-jobs'],
    queryFn: () => api.listProductIntelligenceJobs({ limit: 20 }),
  });
  const sourceRecords = prefill.records ?? [];
  const defaultJobId = sourceRecords.length ? null : (jobsQuery.data?.[0]?.id ?? null);
  const resolvedActiveJobId = activeJobId ?? defaultJobId;
  const detailQuery = useQuery({
    queryKey: ['product-intelligence-job', resolvedActiveJobId],
    queryFn: () => api.getProductIntelligenceJob(resolvedActiveJobId ?? 0),
    enabled: resolvedActiveJobId !== null,
  });
  const historyItems: HistoryItem[] = useMemo(
    () =>
      (jobsQuery.data ?? []).map((job) => ({
        id: job.id,
        status: job.status,
        created_at: job.created_at,
        label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
        meta: `${Number(job.summary?.candidate_count ?? 0)} URLs found`,
      })),
    [jobsQuery.data],
  );
  const detailHydratedOptions = useMemo(
    () => (detailQuery.data ? detailOptions(detailQuery.data.job.options) : DEFAULT_OPTIONS),
    [detailQuery.data],
  );
  const discovery =
    discoveryOverride ?? (detailQuery.data ? detailToDiscovery(detailQuery.data) : null);
  const effectiveOptions = optionsEdited || !detailQuery.data ? options : detailHydratedOptions;
  const effectiveAllowedDomainsText = optionsEdited
    ? allowedDomainsText
    : detailHydratedOptions.allowed_domains.join('\n');
  const effectiveExcludedDomainsText = optionsEdited
    ? excludedDomainsText
    : detailHydratedOptions.excluded_domains.join('\n');
  const visibleSourceRecords = sourceRecords.length
    ? sourceRecords
    : detailQuery.data
      ? detailQuery.data.source_products.map((source) => ({
          id: source.source_record_id,
          run_id: source.source_run_id,
          source_url: source.source_url,
          data: source.payload,
        }))
      : [];
  const activeSourceRunId = sourceRecords.length
    ? (prefill.source_run_id ??
      sourceRecords.find((record) => typeof record.run_id === 'number')?.run_id ??
      null)
    : (detailQuery.data?.job.source_run_id ??
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
    const domains = Array.from(
      new Set(
        (discovery?.candidates ?? [])
          .filter((candidate) => uniqueSelectedUrls.includes(candidate.url))
          .map((candidate) => candidate.domain)
          .filter(Boolean),
      ),
    );
    return { count: uniqueSelectedUrls.length, domains };
  }, [discovery, uniqueSelectedUrls]);

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
      await jobsQuery.refetch();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to discover candidates.');
    } finally {
      setPending(false);
    }
  }

  function toggleUrl(url: string) {
    setSelectedUrls((current) =>
      current.includes(url) ? current.filter((item) => item !== url) : [...current, url],
    );
  }

  function sendSelectedToBatchCrawl() {
    if (!uniqueSelectedUrls.length) return;
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({ domain: 'commerce', urls: uniqueSelectedUrls }),
    );
    router.replace('/crawl?module=pdp&mode=batch' as Route);
  }

  function toggleAllUrls() {
    const filteredUrls = filteredCandidates.map((candidate) => candidate.url).filter(Boolean);
    const allFilteredSelected = filteredUrls.every((url) => selectedUrls.includes(url));
    if (allFilteredSelected && filteredUrls.length > 0) {
      setSelectedUrls((current) => current.filter((url) => !filteredUrls.includes(url)));
    } else {
      setSelectedUrls((current) => Array.from(new Set([...current, ...filteredUrls])));
    }
  }

  function openJob(jobId: number) {
    setActiveJobId(jobId);
    setDiscoveryOverride(null);
    setSelectedUrls([]);
    setOptionsEdited(false);
  }

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
    openJob,
    pending,
    resolvedActiveJobId,
    searchText,
    selectedDomainSummary,
    selectedUrls,
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
