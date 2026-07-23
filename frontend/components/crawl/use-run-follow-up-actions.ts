import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import type { CrawlRecord, CrawlRun } from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import {
  storeDataEnrichmentPrefill,
  storeProductIntelligencePrefill,
} from '../../lib/crawl/prefill';
import { extractRecordUrl, inferDomainFromSurface, isListingRun, uniqueStrings } from './shared';

type UseRunFollowUpActionsOptions = {
  run: CrawlRun | undefined;
  selectedRecords: CrawlRecord[];
  batchSourceRecords: CrawlRecord[];
};

export function useRunFollowUpActions({
  run,
  selectedRecords,
  batchSourceRecords,
}: Readonly<UseRunFollowUpActionsOptions>) {
  const navigate = useNavigate();
  const resultUrls = useMemo(
    () => uniqueStrings(batchSourceRecords.map((record) => extractRecordUrl(record))),
    [batchSourceRecords],
  );
  const selectedResultUrls = useMemo(
    () => uniqueStrings(selectedRecords.map((record) => extractRecordUrl(record))),
    [selectedRecords],
  );
  const listingRun = useMemo(() => isListingRun(run), [run]);
  const ecommerceDetailRun = String(run?.surface ?? '') === 'ecommerce_detail';
  const batchFromResultsUrls = selectedResultUrls.length ? selectedResultUrls : resultUrls;
  const batchFromResultsLabel = selectedResultUrls.length
    ? `Batch Crawl Selected (${selectedResultUrls.length})`
    : `Batch Crawl (${resultUrls.length})`;
  const productIntelligenceRecords = selectedRecords.length ? selectedRecords : batchSourceRecords;
  const productIntelligenceLabel = selectedRecords.length
    ? `Product Intelligence Selected (${selectedRecords.length})`
    : `Product Intelligence (${productIntelligenceRecords.length})`;
  const dataEnrichmentRecords = selectedRecords.length ? selectedRecords : batchSourceRecords;
  const dataEnrichmentLabel = selectedRecords.length
    ? `Enrich Selected (${selectedRecords.length})`
    : `Enrich Records (${dataEnrichmentRecords.length})`;

  function startBatchCrawl() {
    if (!batchFromResultsUrls.length) {
      return;
    }
    const domain = inferDomainFromSurface(run?.surface) ?? 'commerce';
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({ domain, urls: batchFromResultsUrls }),
    );
    navigate('/crawl?module=pdp&mode=batch');
  }

  function startProductIntelligence() {
    if (!productIntelligenceRecords.length) {
      return;
    }
    storeProductIntelligencePrefill({
      source_run_id: run?.id ?? null,
      source_domain: run?.url ?? '',
      records: productIntelligenceRecords.map((record) => ({
        id: record.id,
        run_id: record.run_id,
        source_url: record.source_url,
        data: record.data,
      })),
    });
    navigate('/product-intelligence');
  }

  function startDataEnrichment() {
    if (!dataEnrichmentRecords.length) {
      return;
    }
    storeDataEnrichmentPrefill({
      source_run_id: run?.id ?? null,
      records: dataEnrichmentRecords.map((record) => ({
        id: record.id,
        run_id: record.run_id,
        source_url: record.source_url,
        data: record.data,
      })),
    });
    navigate('/data-enrichment');
  }

  return {
    listingRun,
    ecommerceDetailRun,
    batchFromResultsUrls,
    batchFromResultsLabel,
    productIntelligenceRecords,
    productIntelligenceLabel,
    dataEnrichmentRecords,
    dataEnrichmentLabel,
    startBatchCrawl,
    startProductIntelligence,
    startDataEnrichment,
  };
}
