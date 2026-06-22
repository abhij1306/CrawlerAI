import { useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';
import type { OutputTabKey } from './shared';

const outputTabKeys = [
  'table',
  'json',
  'logs',
  'learning',
] as const satisfies readonly OutputTabKey[];

function isOutputTabKey(value: string): value is OutputTabKey {
  return outputTabKeys.some((key) => key === value);
}

function parseOutputTab(value: string | null): OutputTabKey {
  return value !== null && isOutputTabKey(value) ? value : 'table';
}

type UseRunOutputStateOptions = {
  failedRunWithoutRecords: boolean;
  showLearningTab: boolean;
};

export function useRunOutputState({
  failedRunWithoutRecords,
  showLearningTab,
}: Readonly<UseRunOutputStateOptions>) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [tablePage, setTablePage] = useState(1);
  const [jsonVisibleCount, setJsonVisibleCount] = useState<number>(
    CRAWL_DEFAULTS.TABLE_PAGE_SIZE,
  );
  const [historyOpen, setHistoryOpen] = useState(false);
  const requestedOutputTab = parseOutputTab(searchParams.get('output'));
  const outputTab =
    failedRunWithoutRecords && requestedOutputTab === 'table'
      ? 'logs'
      : requestedOutputTab === 'learning' && !showLearningTab
        ? 'table'
        : requestedOutputTab;

  const setOutputTab = useCallback(
    (next: OutputTabKey) => {
      setSearchParams(
        (current) => {
          const updated = new URLSearchParams(current);
          if (next === 'table') updated.delete('output');
          else updated.set('output', next);
          return updated;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return {
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
  };
}
