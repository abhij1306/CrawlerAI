import { EyeOff, TerminalSquare } from 'lucide-react';
import { useState } from 'react';

import type { ApiKeyCreated, PublicApiCapabilities } from '@lib/api/api-access';
import { detectDefaultShell } from '@lib/ui/detect-shell';
import { Button } from '@ui/button';
import { CodeBlock, TabBar } from '@ui/patterns';
import {
  mcpLaunchCommand,
  mcpLoopbackCommand,
  publicApiBaseUrl,
  restExtractCommand,
  restRequestCommand,
  SHELL_OPTIONS,
  shellLabel,
  type SetupShell,
} from './api-access-commands';

export function ApiAccessSetup({
  created,
  capabilities,
  probeError,
  onDismiss,
}: Readonly<{
  created: ApiKeyCreated;
  capabilities: PublicApiCapabilities | null;
  probeError: string;
  onDismiss: () => void;
}>) {
  const [shell, setShell] = useState<SetupShell>(detectDefaultShell);
  const apiBaseUrl = publicApiBaseUrl();
  const label = shellLabel(shell);

  return (
    <div className="space-y-4 rounded-lg border border-accent/30 bg-accent/5 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="type-subheading m-0">Save this key now</p>
          <p className="type-body m-0 mt-1">
            CrawlerAI stores only its hash. The full key will not be shown again.
          </p>
        </div>
        <Button type="button" variant="quiet" size="sm" onClick={onDismiss}>
          <EyeOff className="size-3.5" /> Dismiss
        </Button>
      </div>

      <CodeBlock label="API key" value={created.api_key} />
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold tracking-wide text-muted uppercase">Platform</span>
        <TabBar<SetupShell>
          value={shell}
          onChange={setShell}
          compact
          size="sm"
          options={[...SHELL_OPTIONS]}
        />
      </div>
      <CodeBlock
        label={`Test REST API · ${label}`}
        value={restRequestCommand(apiBaseUrl, created.api_key, shell)}
      />
      <CodeBlock
        label={`Extract one product · ${label}`}
        value={restExtractCommand(apiBaseUrl, created.api_key, shell)}
      />
      <CodeBlock
        label={`Launch local MCP process · ${label}`}
        value={mcpLaunchCommand(apiBaseUrl, created.api_key, shell)}
      />
      <CodeBlock
        label={`Optional loopback SSE MCP · ${label}`}
        value={mcpLoopbackCommand(apiBaseUrl, created.api_key, shell)}
      />

      <div className="flex items-start gap-2 rounded-md border border-border bg-panel px-3 py-2 text-base text-secondary">
        <TerminalSquare className="mt-0.5 size-4 shrink-0 text-muted" />
        <div>
          Prefer one local stdio process per MCP client from the backend directory. Each process
          uses that client's own API key. Public hosted MCP is not supported. Optional SSE is
          restricted to a literal loopback address and shares its key with trusted local clients.
          {capabilities ? (
            <p className="mt-1 text-success-text">
              API verified. Tools: {capabilities.tools.join(', ')}.
            </p>
          ) : null}
          {probeError ? (
            <p className="mt-1 text-warning-text">API check failed: {probeError}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
