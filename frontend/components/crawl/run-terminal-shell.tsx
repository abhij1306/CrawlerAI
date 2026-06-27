import type { ReactNode } from 'react';

import type { CrawlRun } from '../../lib/api/types';
import { InlineAlert, RunWorkspaceShell } from '../ui/patterns';
import { Card } from '../ui/primitives';

type RunTerminalShellProps = {
  run: CrawlRun | undefined;
  runErrorMessage: string;
  actionError: string;
  actions: ReactNode;
  tabs: ReactNode;
  summary: ReactNode;
  children: ReactNode;
};

export function RunTerminalShell({
  run,
  runErrorMessage,
  actionError,
  actions,
  tabs,
  summary,
  children,
}: Readonly<RunTerminalShellProps>) {
  return (
    <div className="space-y-4">
      <Card className="section-card">
        {runErrorMessage ? <InlineAlert tone="danger" message={runErrorMessage} /> : null}
        {actionError ? <InlineAlert tone="danger" message={actionError} /> : null}
        <RunWorkspaceShell
          header={
            run?.url ? (
              <a
                href={run.url}
                target="_blank"
                rel="noreferrer"
                className="link-accent type-body block truncate underline-offset-2 hover:underline"
              >
                {run.url}
              </a>
            ) : (
              <p className="type-body text-muted">Waiting for completed run data.</p>
            )
          }
          actions={actions}
          tabs={tabs}
          summary={summary}
          content={children}
        />
      </Card>
    </div>
  );
}
