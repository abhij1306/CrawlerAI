import type { RefObject } from 'react';

import type { CrawlRecord, RunEvent } from '../../lib/api/types';
import { RunEventTerminal } from './run-event-terminal';

type RunEventsOutputProps = {
  events: RunEvent[];
  records: CrawlRecord[];
  requestedFields: string[];
  viewportRef: RefObject<HTMLDivElement | null>;
  nowMs: number;
};

export function RunEventsOutput({
  events,
  records,
  requestedFields,
  viewportRef,
  nowMs,
}: Readonly<RunEventsOutputProps>) {
  return (
    <div className="min-h-[55vh]">
      <RunEventTerminal
        events={events}
        records={records}
        requestedFields={requestedFields}
        viewportRef={viewportRef}
        nowMs={nowMs}
      />
    </div>
  );
}
