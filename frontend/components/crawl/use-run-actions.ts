import { useState } from 'react';

import { api } from '../../lib/api';

type RefetchableQuery = {
  refetch: () => Promise<unknown>;
};

type UseRunActionsOptions = {
  runId: number;
  refreshQueries: ReadonlyArray<RefetchableQuery>;
};

export function useRunActions({ runId, refreshQueries }: Readonly<UseRunActionsOptions>) {
  const [killPending, setKillPending] = useState(false);
  const [error, setError] = useState('');

  function downloadExport(kind: 'csv' | 'json') {
    setError('');
    const filename = `run-${runId}.${kind}`;
    try {
      const href = kind === 'csv' ? api.exportCsv(runId) : api.exportJson(runId);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = filename;
      anchor.style.display = 'none';
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch (downloadError) {
      setError(
        downloadError instanceof Error ? downloadError.message : 'Unable to download export.',
      );
    }
  }

  async function killRun() {
    setKillPending(true);
    setError('');
    try {
      await api.killCrawl(runId);
      await Promise.all(refreshQueries.map((query) => query.refetch()));
    } catch (killError) {
      setError(killError instanceof Error ? killError.message : 'Unable to kill crawl.');
    } finally {
      setKillPending(false);
    }
  }

  return {
    killPending,
    error,
    downloadExport,
    killRun,
  };
}
