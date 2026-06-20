import { useNavigate } from 'react-router-dom';
import { useMemo, useState } from 'react';
import { HistoryDrawer } from '../ui/history-drawer';
import { parseApiDate } from '../../lib/format/date';
import { extractionVerdict } from './shared';

import { RunLearningPanel } from './run-learning-panel';
import { RunLiveWorkspace } from './run-live-workspace';
import { RunLogsOutput } from './run-logs-output';
import {
  JSON_PREVIEW_INCREMENT,
  RunJsonOutput,
  RunTableOutput,
} from './run-records-output';
import {
  RunLoadError,
  RunLoadingState,
  RunPageHeader,
  RunPanelErrorState,
} from './run-page-status';
import { RunOutputSummary, RunOutputTabs, useRunSummary } from './run-summary';
import { RunTerminalShell } from './run-terminal-shell';
import { RunWorkspaceActions } from './run-workspace-actions';
import { useLiveClock, useTerminalSync } from './use-run-polling';
import { useRunActions } from './use-run-actions';
import { useRunFollowUpActions } from './use-run-follow-up-actions';
import { useRunHistory } from './use-run-history';
import { useRunLogStream } from './use-run-log-stream';
import { useRunOutputState } from './use-run-output-state';
import { useRunPanelErrors } from './use-run-panel-errors';
import { useRunRecipe } from './use-run-recipe';
import { useRunRecipeActions } from './use-run-recipe-actions';
import { useRunRecordSelection } from './use-run-record-selection';
import { useRunRecords } from './use-run-records';
import { useRunWorkspace } from './use-run-workspace';

type CrawlRunScreenProps = { runId: number };

export function CrawlRunScreen({ runId }: Readonly<CrawlRunScreenProps>) {
  return <CrawlRunWorkspace key={runId} runId={runId} />;
}

function CrawlRunWorkspace({ runId }: Readonly<CrawlRunScreenProps>) {
  const navigate = useNavigate();
  const [sessionStartMs] = useState(() => Date.now());
  const { runQuery, run, live, terminal } = useRunWorkspace(runId);
  const localNow = useLiveClock(live);
  const { refetch: refetchRunQuery } = runQuery;
  const runCreatedMs = run?.created_at ? parseApiDate(run.created_at).getTime() : null;
  const effectiveStartMs = runCreatedMs ?? sessionStartMs;
  const failedRunWithoutRecords = Boolean(
    run &&
    (run.status === 'failed' || run.status === 'proxy_exhausted') &&
    Number(run?.result_summary?.record_count ?? 0) === 0,
  );
  const showRunLearningTab = Boolean(run?.run_type === 'crawl' && terminal);
  const {
    outputTab,
    setOutputTab,
    selectedIds,
    setSelectedIds,
    tablePage,
    setTablePage,
    jsonVisibleCount,
    setJsonVisibleCount,
    historyOpen,
    setHistoryOpen,
  } = useRunOutputState({
    failedRunWithoutRecords,
    showLearningTab: showRunLearningTab,
  });
  const verdict = extractionVerdict(run);
  const shouldFetchLogs = Boolean(run) && (live || outputTab === 'logs');

  const {
    tableRecordsQuery,
    jsonRecordsQuery,
    records,
    tableRecords,
    tableTotal,
    recordsTotal,
    jsonRecords,
    hasMoreTableRecords,
    hasMoreJsonRecords,
    recordsJson,
    recordsFetchCapReached,
    summaryRecordsFromRun,
  } = useRunRecords({
    runId,
    run,
    live,
    terminal,
    outputTab,
    tablePage,
    jsonVisibleCount,
    verdict,
  });
  const {
    query: logsQuery,
    logs,
    online: logSocketOnline,
    liveJumpAvailable,
    viewportRef: logViewportRef,
    jumpToLatest,
  } = useRunLogStream({
    runId,
    enabled: shouldFetchLogs,
    live,
    refetchRun: refetchRunQuery,
  });
  const domainRecipeQuery = useRunRecipe(runId, showRunLearningTab);
  const { refetch: refetchDomainRecipeQuery } = domainRecipeQuery;
  const domainRecipe = domainRecipeQuery.data;
  const {
    pendingKey: recipeActionPending,
    error: recipeActionError,
    applyFieldAction,
  } = useRunRecipeActions({
    runId,
    refetchRecipe: refetchDomainRecipeQuery,
  });
  const {
    killPending,
    error: runActionError,
    downloadExport,
    killRun,
  } = useRunActions({
    runId,
    refreshQueries: [runQuery, logsQuery, tableRecordsQuery, jsonRecordsQuery],
  });
  const { items: historyItems } = useRunHistory();

  const elapsedLabel = useMemo(() => {
    const elapsedMs = Math.max(0, localNow - effectiveStartMs);
    const totalS = Math.floor(elapsedMs / 1000);
    const m = Math.floor(totalS / 60);
    const s = totalS % 60;
    return `${m}m ${String(s).padStart(2, '0')}s`;
  }, [effectiveStartMs, localNow]);
  const showRunLoadingState = runQuery.isLoading && !run;
  const { panels: panelRefreshErrors, retry: retryFailedPanels } = useRunPanelErrors({
    runId,
    live,
    terminal,
    run: runQuery,
    tableRecords: tableRecordsQuery,
    jsonRecords: jsonRecordsQuery,
    logs: logsQuery,
    domainRecipe: domainRecipeQuery,
  });

  useTerminalSync(run, terminal, [runQuery, tableRecordsQuery, jsonRecordsQuery, logsQuery]);

  const {
    visibleColumns,
    filteredTableRecords,
    visibleSelectedIds,
    selectedRecords,
    batchSourceRecords,
  } = useRunRecordSelection({
    outputTab,
    records,
    tableRecords,
    selectedIds,
  });
  const {
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
  } = useRunFollowUpActions({
    run,
    selectedRecords,
    batchSourceRecords,
  });
  const {
    llmSummary,
    summary,
    qualityLevel: completedQualityLevel,
    runErrorMessage,
    emptyRecordsState,
  } = useRunSummary({
    run,
    terminal,
    verdict,
    effectiveStartMs,
    localNow,
    recordsTotal,
    tableTotal,
    visibleFieldCount: visibleColumns.length,
    batchSourceRecords,
    summaryRecordsFromRun,
  });
  function resetToConfig() {
    navigate('/crawl?module=category&mode=single');
  }

  if (runQuery.error) {
    return <RunLoadError error={runQuery.error} onNewCrawl={resetToConfig} />;
  }

  return (
    <div className="page-stack gap-4">
      <RunPageHeader run={run} onNewCrawl={resetToConfig} />

      {showRunLoadingState ? <RunLoadingState runId={runId} /> : null}

      <RunPanelErrorState
        panels={panelRefreshErrors}
        onRetry={() => void retryFailedPanels()}
      />
      {!showRunLoadingState && !terminal ? (
        <RunLiveWorkspace
          run={run}
          logs={logs}
          records={batchSourceRecords}
          elapsedLabel={elapsedLabel}
          socketOnline={logSocketOnline}
          liveJumpAvailable={liveJumpAvailable}
          viewportRef={logViewportRef}
          killPending={killPending}
          onJumpToLatest={jumpToLatest}
          onKill={() => void killRun()}
        />
      ) : null}

      {!showRunLoadingState && terminal ? (
        <RunTerminalShell
          run={run}
          runErrorMessage={runErrorMessage}
          actionError={runActionError}
          actions={
            <RunWorkspaceActions
              showBatch={listingRun && batchFromResultsUrls.length > 0}
              batchLabel={batchFromResultsLabel}
              showProductIntelligence={
                (listingRun || ecommerceDetailRun) && productIntelligenceRecords.length > 0
              }
              productIntelligenceLabel={productIntelligenceLabel}
              showDataEnrichment={ecommerceDetailRun && dataEnrichmentRecords.length > 0}
              dataEnrichmentLabel={dataEnrichmentLabel}
              onBatch={startBatchCrawl}
              onProductIntelligence={startProductIntelligence}
              onDataEnrichment={startDataEnrichment}
              onDownloadCsv={() => downloadExport('csv')}
              onDownloadJson={() => downloadExport('json')}
              onHistory={() => setHistoryOpen(true)}
            />
          }
          tabs={
            <RunOutputTabs
              value={outputTab}
              recordCount={summary.records}
              showLearning={showRunLearningTab}
              onChange={setOutputTab}
            />
          }
          summary={
            <RunOutputSummary
              llmRequested={llmSummary.requested}
              llmTouchedRecords={llmSummary.touchedRecords}
              llmTouchedFields={llmSummary.touchedFields}
              duration={summary.duration}
              verdict={verdict}
              quality={completedQualityLevel}
            />
          }
        >
          <>
                  {outputTab === 'table' ? (
                    <RunTableOutput
                      loading={tableRecordsQuery.isLoading}
                      records={filteredTableRecords}
                      visibleColumns={visibleColumns}
                      selectedIds={visibleSelectedIds}
                      total={tableTotal}
                      hasMore={hasMoreTableRecords}
                      emptyState={emptyRecordsState}
                      onSelectAll={(checked) =>
                        setSelectedIds(
                          checked ? filteredTableRecords.map((record) => record.id) : [],
                        )
                      }
                      onToggleRow={(id, checked) =>
                        setSelectedIds((current) =>
                          checked
                            ? Array.from(new Set([...current, id]))
                            : current.filter((value) => value !== id),
                        )
                      }
                      onLoadMore={() => setTablePage((current) => current + 1)}
                    />
                  ) : null}

                  {outputTab === 'json' ? (
                    <RunJsonOutput
                      records={records}
                      recordsJson={recordsJson}
                      visibleCount={jsonRecords.length}
                      total={recordsTotal}
                      hasMore={hasMoreJsonRecords}
                      fetchCapReached={recordsFetchCapReached}
                      onLoadMore={() =>
                        setJsonVisibleCount((current) => current + JSON_PREVIEW_INCREMENT)
                      }
                    />
                  ) : null}

                  {outputTab === 'logs' ? (
                    <RunLogsOutput
                      logs={logs}
                      records={batchSourceRecords}
                      requestedFields={run?.requested_fields ?? []}
                      viewportRef={logViewportRef}
                    />
                  ) : null}

                  {outputTab === 'learning' ? (
                    <div className="min-h-[55vh] space-y-4">
                      <RunLearningPanel
                        loading={domainRecipeQuery.isLoading}
                        recipe={domainRecipe}
                        pendingKey={recipeActionPending}
                        error={recipeActionError}
                        onFieldAction={applyFieldAction}
                      />
                    </div>
                  ) : null}
          </>
        </RunTerminalShell>
      ) : null}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={runId}
        onSelect={(id) => navigate(`/crawl?run_id=${id}`)}
        title="Crawl History"
      />
    </div>
  );
}
