import { useNavigate } from 'react-router-dom';
import { useMemo, useState } from 'react';
import { HistoryDrawer } from '../ui/history-drawer';
import { extractionVerdict } from './shared';
import { CrawlTerminalTabContent } from './crawl-terminal-tab-content';

import { RunLiveWorkspace } from './run-live-workspace';
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
import { followUpVisibility, useRunWorkspace, workspaceRunState } from './use-run-workspace';

type CrawlRunScreenProps = { runId: number };

export function CrawlRunScreen({ runId }: Readonly<CrawlRunScreenProps>) {
  return <CrawlRunWorkspace key={runId} runId={runId} />;
}

// skipcq: JS-0067 -- pure orchestrator: all UI in named sub-components, all data in custom hooks
function CrawlRunWorkspace({ runId }: Readonly<CrawlRunScreenProps>) {
  const navigate = useNavigate();
  const [sessionStartMs] = useState(() => Date.now());
  const { runQuery, run, live, terminal } = useRunWorkspace(runId);
  const localNow = useLiveClock(live);
  const { refetch: refetchRunQuery } = runQuery;
  const {
    effectiveStartMs,
    failedRunWithoutRecords,
    showLearningTab: showRunLearningTab,
    requestedFields,
  } = workspaceRunState(run, terminal, sessionStartMs);
  const {
    outputTab,
    setOutputTab,
    selectedIds,
    setSelectedIds,
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
    fetchNextTablePage,
    fetchNextJsonPage,
    isFetchingNextTablePage,
    isFetchingNextJsonPage,
    summaryRecordsFromRun,
  } = useRunRecords({
    runId,
    run,
    live,
    terminal,
    outputTab,
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
  const domainRecipeQuery = useRunRecipe(runId, showRunLearningTab && outputTab === 'learning');
  const { refetch: refetchDomainRecipeQuery } = domainRecipeQuery;
  const domainRecipe = domainRecipeQuery.data;
  const {
    pendingKey: recipeActionPending,
    error: recipeActionError,
    activateGroundedCorrection,
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
  const { items: historyItems, prepareRun: prepareHistoryRun } = useRunHistory(historyOpen);

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
    selectAllVisibleTableRecords,
    toggleSelectedRecord,
  } = useRunRecordSelection({
    outputTab,
    records,
    tableRecords,
    selectedIds,
    setSelectedIds,
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
  const actionVisibility = followUpVisibility({
    listingRun,
    ecommerceDetailRun,
    batchCount: batchFromResultsUrls.length,
    productIntelligenceCount: productIntelligenceRecords.length,
    dataEnrichmentCount: dataEnrichmentRecords.length,
  });
  const { showBatch, showProductIntelligence, showDataEnrichment } = actionVisibility;
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

  const terminalActions = useMemo(
    () => (
      <RunWorkspaceActions
        showBatch={showBatch}
        batchLabel={batchFromResultsLabel}
        showProductIntelligence={showProductIntelligence}
        productIntelligenceLabel={productIntelligenceLabel}
        showDataEnrichment={showDataEnrichment}
        dataEnrichmentLabel={dataEnrichmentLabel}
        onBatch={startBatchCrawl}
        onProductIntelligence={startProductIntelligence}
        onDataEnrichment={startDataEnrichment}
        onDownloadCsv={() => downloadExport('csv')}
        onDownloadJson={() => downloadExport('json')}
        onHistory={() => setHistoryOpen(true)}
      />
    ),
    [
      showBatch,
      batchFromResultsLabel,
      showProductIntelligence,
      productIntelligenceLabel,
      showDataEnrichment,
      dataEnrichmentLabel,
      startBatchCrawl,
      startProductIntelligence,
      startDataEnrichment,
      downloadExport,
      setHistoryOpen,
    ],
  );

  const terminalTabs = useMemo(
    () => (
      <RunOutputTabs
        value={outputTab}
        recordCount={summary.records}
        showLearning={showRunLearningTab}
        onChange={setOutputTab}
      />
    ),
    [outputTab, summary.records, showRunLearningTab, setOutputTab],
  );

  const terminalSummary = useMemo(
    () => (
      <RunOutputSummary
        llmRequested={llmSummary.requested}
        llmTouchedRecords={llmSummary.touchedRecords}
        llmTouchedFields={llmSummary.touchedFields}
        duration={summary.duration}
        verdict={verdict}
        quality={completedQualityLevel}
      />
    ),
    [
      llmSummary.requested,
      llmSummary.touchedRecords,
      llmSummary.touchedFields,
      summary.duration,
      verdict,
      completedQualityLevel,
    ],
  );

  if (runQuery.error) {
    return <RunLoadError error={runQuery.error} onNewCrawl={resetToConfig} />;
  }

  return (
    <div className="page-stack gap-4">
      <RunPageHeader run={run} onNewCrawl={resetToConfig} />

      {showRunLoadingState ? <RunLoadingState runId={runId} /> : null}

      <RunPanelErrorState panels={panelRefreshErrors} onRetry={() => void retryFailedPanels()} />
      {!showRunLoadingState && !terminal ? (
        <RunLiveWorkspace
          run={run}
          logs={logs}
          records={batchSourceRecords}
          elapsedLabel={elapsedLabel}
          nowMs={localNow}
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
          actions={terminalActions}
          tabs={terminalTabs}
          summary={terminalSummary}
        >
          <CrawlTerminalTabContent
            outputTab={outputTab}
            emptyRecordsState={emptyRecordsState}
            table={{
              tableRecordsLoading: tableRecordsQuery.isLoading || isFetchingNextTablePage,
              filteredTableRecords,
              visibleColumns,
              visibleSelectedIds,
              tableTotal,
              hasMoreTableRecords,
              onSelectAllRecords: selectAllVisibleTableRecords,
              onToggleRecord: toggleSelectedRecord,
              onLoadMoreTableRecords: () => void fetchNextTablePage(),
            }}
            json={{
              jsonRecordsLoading: jsonRecordsQuery.isLoading || isFetchingNextJsonPage,
              records,
              recordsJson,
              jsonRecordsLength: jsonRecords.length,
              recordsTotal,
              hasMoreJsonRecords,
              recordsFetchCapReached,
              setJsonVisibleCount: (updater) => {
                setJsonVisibleCount(updater);
                void fetchNextJsonPage();
              },
            }}
            logs={{
              logs,
              batchSourceRecords,
              requestedFields,
              logViewportRef,
              nowMs: localNow,
            }}
            learning={{
              domainRecipeLoading: domainRecipeQuery.isLoading,
              domainRecipe,
              recipeActionPending,
              recipeActionError,
              activateGroundedCorrection,
            }}
          />
        </RunTerminalShell>
      ) : null}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={runId}
        onSelect={(id) => {
          prepareHistoryRun(id);
          navigate(`/crawl?run_id=${id}`);
        }}
        title="Crawl History"
      />
    </div>
  );
}
