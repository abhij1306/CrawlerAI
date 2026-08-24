import { Check, Copy, EyeOff, TerminalSquare } from 'lucide-react';
import { useState } from 'react';

import { getApiBaseUrl } from '@/api/client';
import type { ApiKeyCreated, PublicApiCapabilities } from '@lib/api/api-access';
import { Button } from '@ui/button';
import { InlineAlert, TabBar } from '@ui/patterns';

export type SetupShell = 'powershell' | 'bash';

function quotePowerShell(value: string) {
  return `'${value.replaceAll("'", "''")}'`;
}

function quoteBash(value: string) {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function quoteForShell(value: string, shell: SetupShell) {
  return shell === 'powershell' ? quotePowerShell(value) : quoteBash(value);
}

export function publicApiBaseUrl() {
  return `${getApiBaseUrl()}/api/v1`;
}

export function mcpLaunchCommand(
  apiBaseUrl: string,
  apiKey: string,
  shell: SetupShell = 'powershell',
) {
  const keyAssignment = `CRAWLERAI_API_KEY=${quoteForShell(apiKey, shell)}`;
  const urlAssignment = `CRAWLERAI_API_BASE_URL=${quoteForShell(apiBaseUrl, shell)}`;
  const transportAssignment = `CRAWLERAI_MCP_TRANSPORT=${quoteForShell('stdio', shell)}`;
  return [
    shell === 'powershell' ? `$env:${keyAssignment}` : `export ${keyAssignment}`,
    shell === 'powershell' ? `$env:${urlAssignment}` : `export ${urlAssignment}`,
    shell === 'powershell' ? `$env:${transportAssignment}` : `export ${transportAssignment}`,
    'python -m app.mcp_server.server',
  ].join('\n');
}

export function mcpLoopbackCommand(
  apiBaseUrl: string,
  apiKey: string,
  shell: SetupShell = 'powershell',
) {
  const assignments = [
    ['CRAWLERAI_API_KEY', apiKey],
    ['CRAWLERAI_API_BASE_URL', apiBaseUrl],
    ['CRAWLERAI_MCP_TRANSPORT', 'sse'],
    ['CRAWLERAI_MCP_HOST', '127.0.0.1'],
  ].map(([name, value]) => {
    const assignment = `${name}=${quoteForShell(value, shell)}`;
    return shell === 'powershell' ? `$env:${assignment}` : `export ${assignment}`;
  });
  return [...assignments, 'python -m app.mcp_server.server'].join('\n');
}

export function restRequestCommand(apiBaseUrl: string, apiKey: string, shell: SetupShell) {
  const curl = shell === 'powershell' ? 'curl.exe' : 'curl';
  const authorization = quoteForShell(`Authorization: Bearer ${apiKey}`, shell);
  const capabilitiesUrl = quoteForShell(`${apiBaseUrl}/capabilities`, shell);
  return `${curl} -H ${authorization} ${capabilitiesUrl}`;
}

export function restExtractCommand(apiBaseUrl: string, apiKey: string, shell: SetupShell) {
  const curl = shell === 'powershell' ? 'curl.exe' : 'curl';
  const authorization = quoteForShell(`Authorization: Bearer ${apiKey}`, shell);
  const contentType = quoteForShell('Content-Type: application/json', shell);
  const payload = quoteForShell(
    JSON.stringify({
      url: 'https://example.com/product',
      surface: 'ecommerce',
      fields: ['title', 'price'],
    }),
    shell,
  );
  const extractUrl = quoteForShell(`${apiBaseUrl}/extract`, shell);
  return `${curl} -X POST -H ${authorization} -H ${contentType} --data-raw ${payload} ${extractUrl}`;
}

function SetupBlock({ label, value }: Readonly<{ label: string; value: string }>) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopyError('');
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopyError('Clipboard unavailable. Select and copy the value manually.');
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold tracking-wide text-muted uppercase">{label}</span>
        <Button type="button" variant="quiet" size="sm" onClick={() => void copy()}>
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-md border border-border bg-background px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap text-secondary">
        {value}
      </pre>
      {copyError ? <InlineAlert tone="warning" message={copyError} /> : null}
    </div>
  );
}

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
  const [shell, setShell] = useState<SetupShell>('powershell');
  const apiBaseUrl = publicApiBaseUrl();
  const shellLabel = shell === 'powershell' ? 'PowerShell' : 'macOS / Linux Bash';

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

      <SetupBlock label="API key" value={created.api_key} />
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold tracking-wide text-muted uppercase">Shell</span>
        <TabBar<SetupShell>
          value={shell}
          onChange={setShell}
          compact
          size="sm"
          options={[
            { value: 'powershell', label: 'PowerShell' },
            { value: 'bash', label: 'Bash' },
          ]}
        />
      </div>
      <SetupBlock
        label={`Test REST API · ${shellLabel}`}
        value={restRequestCommand(apiBaseUrl, created.api_key, shell)}
      />
      <SetupBlock
        label={`Extract one product · ${shellLabel}`}
        value={restExtractCommand(apiBaseUrl, created.api_key, shell)}
      />
      <SetupBlock
        label={`Launch local MCP process · ${shellLabel}`}
        value={mcpLaunchCommand(apiBaseUrl, created.api_key, shell)}
      />
      <SetupBlock
        label={`Optional loopback SSE MCP · ${shellLabel}`}
        value={mcpLoopbackCommand(apiBaseUrl, created.api_key, shell)}
      />

      <div className="flex items-start gap-2 rounded-md border border-border bg-panel px-3 py-2 text-sm text-secondary">
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
