import { useEffect, useMemo, useRef } from 'react';

import { telemetryErrorPayload, trackEvent } from '../../lib/telemetry/events';

type RefreshablePanel = {
  error: unknown;
  refetch: () => Promise<unknown>;
};

type UseRunPanelErrorsOptions = {
  runId: number;
  live: boolean;
  terminal: boolean;
  run: RefreshablePanel;
  tableRecords: RefreshablePanel;
  jsonRecords: RefreshablePanel;
  logs: RefreshablePanel;
  domainRecipe: RefreshablePanel;
};

export function useRunPanelErrors({
  runId,
  live,
  terminal,
  run,
  tableRecords,
  jsonRecords,
  logs,
  domainRecipe,
}: Readonly<UseRunPanelErrorsOptions>) {
  const reportedEventKeysRef = useRef(new Set<string>());
  const panels = useMemo(
    () =>
      [
        {
          key: 'run',
          label: 'run',
          error: run.error,
          refetch: run.refetch,
        },
        {
          key: 'records',
          label: 'records',
          error: tableRecords.error ?? jsonRecords.error,
          refetch: async () => {
            const tasks: Array<Promise<unknown>> = [];
            if (tableRecords.error) tasks.push(tableRecords.refetch());
            if (jsonRecords.error) tasks.push(jsonRecords.refetch());
            await Promise.allSettled(tasks);
          },
        },
        {
          key: 'logs',
          label: 'logs',
          error: logs.error,
          refetch: logs.refetch,
        },
        {
          key: 'domain-recipe',
          label: 'domain recipe',
          error: domainRecipe.error,
          refetch: domainRecipe.refetch,
        },
      ].filter((panel) => panel.error),
    [domainRecipe, jsonRecords, logs, run, tableRecords],
  );

  useEffect(() => {
    for (const panel of panels) {
      const message = panel.error instanceof Error ? panel.error.message : 'Unknown error';
      const eventKey = `${runId}:${panel.key}:${message}`;
      if (reportedEventKeysRef.current.has(eventKey)) continue;
      reportedEventKeysRef.current.add(eventKey);
      trackEvent(
        'run_screen_poll_error_rate',
        telemetryErrorPayload(panel.error, {
          run_id: runId,
          panel: panel.key,
          live,
          terminal,
        }),
      );
    }
  }, [live, panels, runId, terminal]);

  async function retry() {
    await Promise.allSettled(panels.map((panel) => panel.refetch()));
  }

  return { panels, retry };
}
