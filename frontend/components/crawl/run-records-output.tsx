import { Copy } from 'lucide-react';

import type { CrawlRecord } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import { syntaxHighlightJsonNodes } from '../../lib/ui/syntax';
import { DataRegionEmpty, DataRegionLoading, InlineAlert } from '../ui/patterns';
import { Button } from '../ui/primitives';
import { copyJson } from '../../lib/crawl/record-utils';
import { RecordsTable } from './records-table';

type EmptyRecordsState = {
  title: string;
  description: string;
};

type RunTableOutputProps = {
  loading: boolean;
  records: CrawlRecord[];
  visibleColumns: string[];
  selectedIds: number[];
  total: number;
  hasMore: boolean;
  emptyState: EmptyRecordsState;
  onSelectAll: (checked: boolean) => void;
  onToggleRow: (id: number, checked: boolean) => void;
  onLoadMore: () => void;
};

export function RunTableOutput({
  loading,
  records,
  visibleColumns,
  selectedIds,
  total,
  hasMore,
  emptyState,
  onSelectAll,
  onToggleRow,
  onLoadMore,
}: Readonly<RunTableOutputProps>) {
  return (
    <div className="min-h-[55vh] space-y-3">
      {loading && !records.length ? (
        <DataRegionLoading count={5} className="px-0" />
      ) : records.length ? (
        <div className="space-y-3">
          <RecordsTable
            records={records}
            visibleColumns={visibleColumns}
            selectedIds={selectedIds}
            onSelectAll={onSelectAll}
            onToggleRow={onToggleRow}
          />
          {hasMore ? (
            <>
              <div className="table-footer-rail flex items-center justify-between rounded-md px-6 py-2">
                <span>
                  Showing {records.length} of {total} records
                </span>
                <Button variant="neutral" type="button" onClick={onLoadMore}>
                  Load More
                </Button>
              </div>
              <InlineAlert
                tone="warning"
                message={`Table view is currently showing ${records.length} of ${total} records. Load more rows or export JSON/CSV for the full dataset.`}
              />
            </>
          ) : null}
        </div>
      ) : (
        <DataRegionEmpty
          title={emptyState.title}
          description={emptyState.description}
          className="px-0"
        />
      )}
    </div>
  );
}

type RunJsonOutputProps = {
  records: CrawlRecord[];
  recordsJson: string;
  visibleCount: number;
  total: number;
  hasMore: boolean;
  fetchCapReached: boolean;
  onLoadMore: () => void;
};

export function RunJsonOutput({
  records,
  recordsJson,
  visibleCount,
  total,
  hasMore,
  fetchCapReached,
  onLoadMore,
}: Readonly<RunJsonOutputProps>) {
  return (
    <div className="relative min-h-[55vh]">
      <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
        <Button variant="quiet" type="button" onClick={() => void copyJson(records)}>
          <Copy className="size-3.5" />
          Copy
        </Button>
      </div>
      <pre className="crawl-terminal crawl-terminal-json max-h-[72vh] min-h-[55vh]">
        {syntaxHighlightJsonNodes(recordsJson)}
      </pre>
      {hasMore ? (
        <div className="surface-muted text-muted type-body mt-2 flex items-center justify-between rounded-md px-6 py-2">
          <span>
            JSON previewing {visibleCount} of {total} records
          </span>
          <Button variant="neutral" type="button" onClick={onLoadMore}>
            Load More JSON
          </Button>
        </div>
      ) : null}
      {records.length < total && fetchCapReached ? (
        <InlineAlert
          tone="warning"
          message={`JSON preview capped at ${records.length} records for performance. Use JSON export for all ${total} records.`}
        />
      ) : null}
    </div>
  );
}

export const JSON_PREVIEW_INCREMENT = CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4;
