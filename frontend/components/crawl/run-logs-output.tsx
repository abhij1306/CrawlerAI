import type { RefObject } from 'react';

import type { CrawlLog, CrawlRecord } from '../../lib/api/types';
import { LogTerminal } from './log-terminal';

type RunLogsOutputProps = {
  logs: CrawlLog[];
  records: CrawlRecord[];
  requestedFields: string[];
  viewportRef: RefObject<HTMLDivElement | null>;
  nowMs: number;
};

export function RunLogsOutput({
  logs,
  records,
  requestedFields,
  viewportRef,
  nowMs,
}: Readonly<RunLogsOutputProps>) {
  return (
    <div className="min-h-[55vh]">
      <LogTerminal
        logs={logs}
        records={records}
        requestedFields={requestedFields}
        viewportRef={viewportRef}
        nowMs={nowMs}
      />
    </div>
  );
}
