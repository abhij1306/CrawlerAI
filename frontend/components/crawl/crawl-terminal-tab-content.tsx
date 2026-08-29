import React from 'react';
import type {
  CrawlRecord,
  DomainRecipe,
  DomainRecipeFieldLearningItem,
  RunEvent,
} from '../../lib/api/types';
import { JSON_PREVIEW_INCREMENT, RunJsonOutput, RunTableOutput } from './run-records-output';
import { RunEventsOutput } from './run-events-output';
import { RunLearningPanel } from './run-learning-panel';
import type { RecipeActionPendingKey } from './use-run-recipe-actions';

interface TableTabModel {
  tableRecordsLoading: boolean;
  filteredTableRecords: CrawlRecord[];
  visibleColumns: string[];
  visibleSelectedIds: number[];
  tableTotal: number;
  hasMoreTableRecords: boolean;
  onSelectAllRecords: (checked: boolean) => void;
  onToggleRecord: (id: number, checked: boolean) => void;
  onLoadMoreTableRecords: () => void;
}

interface JsonTabModel {
  jsonRecordsLoading: boolean;
  records: CrawlRecord[];
  recordsJson: string;
  jsonRecordsLength: number;
  recordsTotal: number;
  hasMoreJsonRecords: boolean;
  recordsFetchCapReached: boolean;
  setJsonVisibleCount: React.Dispatch<React.SetStateAction<number>>;
}

interface EventsTabModel {
  events: RunEvent[];
  batchSourceRecords: CrawlRecord[];
  requestedFields: string[];
  eventViewportRef: React.RefObject<HTMLDivElement | null>;
  nowMs: number;
}

interface LearningTabModel {
  domainRecipeLoading: boolean;
  domainRecipe: DomainRecipe | undefined;
  recipeActionPending: RecipeActionPendingKey | null;
  recipeActionError: string;
  activateGroundedCorrection: (item: DomainRecipeFieldLearningItem) => Promise<void>;
}

export interface CrawlTerminalTabContentProps {
  outputTab: string;
  emptyRecordsState: { title: string; description: string };
  table: TableTabModel;
  json: JsonTabModel;
  events: EventsTabModel;
  learning: LearningTabModel;
}

export function CrawlTerminalTabContent({
  outputTab,
  emptyRecordsState,
  table,
  json,
  events,
  learning,
}: Readonly<CrawlTerminalTabContentProps>) {
  if (outputTab === 'table') {
    return (
      <RunTableOutput
        loading={table.tableRecordsLoading}
        records={table.filteredTableRecords}
        visibleColumns={table.visibleColumns}
        selectedIds={table.visibleSelectedIds}
        total={table.tableTotal}
        hasMore={table.hasMoreTableRecords}
        emptyState={emptyRecordsState}
        onSelectAll={table.onSelectAllRecords}
        onToggleRow={table.onToggleRecord}
        onLoadMore={table.onLoadMoreTableRecords}
      />
    );
  }

  if (outputTab === 'json') {
    return (
      <RunJsonOutput
        loading={json.jsonRecordsLoading}
        records={json.records}
        recordsJson={json.recordsJson}
        visibleCount={json.jsonRecordsLength}
        total={json.recordsTotal}
        hasMore={json.hasMoreJsonRecords}
        fetchCapReached={json.recordsFetchCapReached}
        emptyState={emptyRecordsState}
        onLoadMore={() => json.setJsonVisibleCount((current) => current + JSON_PREVIEW_INCREMENT)}
      />
    );
  }

  if (outputTab === 'events') {
    return (
      <RunEventsOutput
        events={events.events}
        records={events.batchSourceRecords}
        requestedFields={events.requestedFields}
        viewportRef={events.eventViewportRef}
        nowMs={events.nowMs}
      />
    );
  }

  if (outputTab === 'learning') {
    return (
      <div className="min-h-[55vh] space-y-4">
        <RunLearningPanel
          loading={learning.domainRecipeLoading}
          recipe={learning.domainRecipe}
          pendingKey={learning.recipeActionPending}
          error={learning.recipeActionError}
          onActivateCorrection={(item) => void learning.activateGroundedCorrection(item)}
        />
      </div>
    );
  }

  return null;
}
