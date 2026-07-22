import type { RefObject } from 'react';
import { ChevronsDown, Clock } from 'lucide-react';

import type { CrawlLog, CrawlRecord, CrawlRun } from '../../lib/api/types';
import { ACTIVE_STATUSES } from '../../lib/constants/crawl-statuses';
import { Card } from '../ui/primitives';
import { ActionButton } from '../ui/action-button';
import { LogTerminal } from './log-terminal';

type RunLiveWorkspaceProps = {
  run: CrawlRun | undefined;
  logs: CrawlLog[];
  records: CrawlRecord[];
  elapsedLabel: string;
  socketOnline: boolean;
  liveJumpAvailable: boolean;
  viewportRef: RefObject<HTMLDivElement | null>;
  killPending: boolean;
  onJumpToLatest: () => void;
  onKill: () => void;
};

export function RunLiveWorkspace({
  run,
  logs,
  records,
  elapsedLabel,
  socketOnline,
  liveJumpAvailable,
  viewportRef,
  killPending,
  onJumpToLatest,
  onKill,
}: Readonly<RunLiveWorkspaceProps>) {
  return (
    <Card className="section-card overflow-hidden">
      <header className="flex h-9 items-center justify-between border-b border-border bg-background px-4">
        <span className="type-label-mono flex items-center gap-2 text-muted">
          Live Log Stream
          {socketOnline ? (
            <span
              className="inline-block size-1.5 animate-pulse rounded-full bg-success"
              aria-label="Connected"
            />
          ) : (
            <span
              className="inline-block size-1.5 rounded-full bg-muted"
              aria-label="Disconnected"
            />
          )}
        </span>
        <div className="flex items-center gap-3">
          {run ? (
            <span className="type-body inline-flex h-8 items-center gap-1.5 rounded-sm border border-divider bg-background-elevated px-3 text-foreground tabular-nums">
              <Clock className="size-3.5" />
              {elapsedLabel}
            </span>
          ) : null}

          {liveJumpAvailable ? (
            <button
              type="button"
              onClick={onJumpToLatest}
              className="type-control inline-flex items-center gap-1 rounded-md bg-background-alt px-2.5 py-1.5 shadow-card"
            >
              <ChevronsDown className="size-3.5" aria-hidden="true" />
              Jump to Latest
            </button>
          ) : null}
          <ActionButton
            label={killPending ? 'Killing...' : 'Hard Kill'}
            onClick={onKill}
            disabled={!run || !ACTIVE_STATUSES.has(run.status) || killPending}
            danger
          />
        </div>
      </header>
      <LogTerminal
        logs={logs}
        records={records}
        requestedFields={run?.requested_fields ?? []}
        live
        viewportRef={viewportRef}
      />
    </Card>
  );
}
