import React from 'react';
import type { CrawlRecord, CrawlLog, DomainRecipe } from '../../lib/api/types';
import { JSON_PREVIEW_INCREMENT, RunJsonOutput, RunTableOutput } from './run-records-output';
import { RunLogsOutput } from './run-logs-output';
import { RunLearningPanel } from './run-learning-panel';
import type { RecipeActionPendingKey } from './use-run-recipe-actions';

export interface CrawlTerminalTabContentProps {
  outputTab: string;
  tableRecordsLoading: boolean;
  jsonRecordsLoading: boolean;
  filteredTableRecords: CrawlRecord[];
  visibleColumns: string[];
  visibleSelectedIds: number[];
  tableTotal: number;
  hasMoreTableRecords: boolean;
  emptyRecordsState: { title: string; description: string };
  onSelectAllRecords: (checked: boolean) => void;
  onToggleRecord: (id: number, checked: boolean) => void;
  onLoadMoreTableRecords: () => void;
  records: CrawlRecord[];
  recordsJson: string;
  jsonRecordsLength: number;
  recordsTotal: number;
  hasMoreJsonRecords: boolean;
  recordsFetchCapReached: boolean;
  setJsonVisibleCount: React.Dispatch<React.SetStateAction<number>>;
  logs: CrawlLog[];
  batchSourceRecords: CrawlRecord[];
  requestedFields: string[];
  logViewportRef: React.RefObject<HTMLDivElement | null>;
  domainRecipeLoading: boolean;
  domainRecipe: DomainRecipe | undefined;
  recipeActionPending: RecipeActionPendingKey | null;
  recipeActionError: string;
  applyFieldAction: (
    fieldName: string,
    action: 'keep' | 'reject',
    selectorKind?: string | null,
    selectorValue?: string | null,
    sourceRecordIds?: number[],
  ) => Promise<void>;
}

export function CrawlTerminalTabContent({
  outputTab,
  tableRecordsLoading,
  jsonRecordsLoading,
  filteredTableRecords,
  visibleColumns,
  visibleSelectedIds,
  tableTotal,
  hasMoreTableRecords,
  emptyRecordsState,
  onSelectAllRecords,
  onToggleRecord,
  onLoadMoreTableRecords,
  records,
  recordsJson,
  jsonRecordsLength,
  recordsTotal,
  hasMoreJsonRecords,
  recordsFetchCapReached,
  setJsonVisibleCount,
  logs,
  batchSourceRecords,
  requestedFields,
  logViewportRef,
  domainRecipeLoading,
  domainRecipe,
  recipeActionPending,
  recipeActionError,
  applyFieldAction,
}: Readonly<CrawlTerminalTabContentProps>) {
  if (outputTab === 'table') {
    return (
      <RunTableOutput
        loading={tableRecordsLoading}
        records={filteredTableRecords}
        visibleColumns={visibleColumns}
        selectedIds={visibleSelectedIds}
        total={tableTotal}
        hasMore={hasMoreTableRecords}
        emptyState={emptyRecordsState}
        onSelectAll={onSelectAllRecords}
        onToggleRow={onToggleRecord}
        onLoadMore={onLoadMoreTableRecords}
      />
    );
  }

  if (outputTab === 'json') {
    return (
      <RunJsonOutput
        loading={jsonRecordsLoading}
        records={records}
        recordsJson={recordsJson}
        visibleCount={jsonRecordsLength}
        total={recordsTotal}
        hasMore={hasMoreJsonRecords}
        fetchCapReached={recordsFetchCapReached}
        emptyState={emptyRecordsState}
        onLoadMore={() => setJsonVisibleCount((current) => current + JSON_PREVIEW_INCREMENT)}
      />
    );
  }

  if (outputTab === 'logs') {
    return (
      <RunLogsOutput
        logs={logs}
        records={batchSourceRecords}
        requestedFields={requestedFields}
        viewportRef={logViewportRef}
      />
    );
  }

  if (outputTab === 'learning') {
    return (
      <div className="min-h-[55vh] space-y-4">
        <RunLearningPanel
          loading={domainRecipeLoading}
          recipe={domainRecipe}
          pendingKey={recipeActionPending}
          error={recipeActionError}
          onFieldAction={applyFieldAction}
        />
      </div>
    );
  }

  return null;
}
