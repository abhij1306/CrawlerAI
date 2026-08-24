import { getApiBaseUrl } from '@/api/client';

/**
 * Shell-specific setup commands for the public REST API and the local MCP
 * server.
 *
 * Pure functions, deliberately free of JSX: they are shared by the
 * post-creation panel (which has the real key exactly once) and the persistent
 * "Connect a client" card (which uses a placeholder), so the two can never
 * drift apart.
 *
 * The values stay 'powershell' | 'bash' even though the UI labels them
 * Windows / macOS & Linux — the distinction that matters here is the quoting
 * and env-var syntax, not the operating system.
 */
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

/** Tab labels. The value names the shell; the label names the platform. */
export const SHELL_OPTIONS: ReadonlyArray<{ value: SetupShell; label: string }> = [
  { value: 'powershell', label: 'Windows' },
  { value: 'bash', label: 'macOS & Linux' },
];

export function shellLabel(shell: SetupShell) {
  return shell === 'powershell' ? 'Windows PowerShell' : 'macOS & Linux';
}
