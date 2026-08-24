import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import { TopBarProvider } from '../../components/layout/top-bar-context';
import type { ApiKeyCreated, ApiKeyRecord } from '../../lib/api/api-access';
import {
  mcpLaunchCommand,
  mcpLoopbackCommand,
  restExtractCommand,
  restRequestCommand,
} from './api-access-commands';
import ApiAccessPage from './page-view';

const apiMock = vi.hoisted(() => ({
  listKeys: vi.fn(),
  createKey: vi.fn(),
  deleteKey: vi.fn(),
  getCapabilities: vi.fn(),
}));
const clipboardWrite = vi.fn();

vi.mock('../../lib/api/api-access', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/api/api-access')>();
  return { ...original, apiAccessApi: apiMock };
});

const ACTIVE_KEY: ApiKeyRecord = {
  id: 7,
  name: 'Production MCP',
  key_prefix: 'test-prefix',
  is_active: true,
  last_used_at: null,
  created_at: '2026-08-23T00:00:00Z',
};

const CREATED_KEY: ApiKeyCreated = {
  ...ACTIVE_KEY,
  id: 8,
  name: 'Local MCP',
  key_prefix: 'test-prefix-2',
  api_key: 'test-value',
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/api-access']}>
        <TopBarProvider>
          <ApiAccessPage />
        </TopBarProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listKeys.mockResolvedValue([ACTIVE_KEY]);
  apiMock.createKey.mockResolvedValue(CREATED_KEY);
  apiMock.deleteKey.mockResolvedValue(undefined);
  apiMock.getCapabilities.mockResolvedValue({
    version: 'v1',
    surfaces: ['ecommerce'],
    tools: ['extract_product', 'check_domain', 'list_capabilities'],
    deferred: ['extract_batch'],
    deployment: 'self-hosted',
    mcp: { default_transport: 'stdio', network_scope: 'loopback-only', hosted: false },
  });
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: clipboardWrite.mockResolvedValue(undefined) },
  });
});

describe('API & MCP access page', () => {
  it('quotes PowerShell and Bash commands without changing secret values', () => {
    const apiBaseUrl = "https://api.example.test/o'hare/api/v1";
    const apiKey = "test'value";

    expect(restRequestCommand(apiBaseUrl, apiKey, 'powershell')).toBe(
      "curl.exe -H 'Authorization: Bearer test''value' 'https://api.example.test/o''hare/api/v1/capabilities'",
    );
    expect(mcpLaunchCommand(apiBaseUrl, apiKey, 'bash')).toContain(
      `export CRAWLERAI_API_KEY='test'"'"'value'`,
    );
    expect(mcpLaunchCommand(apiBaseUrl, apiKey, 'bash')).toContain(
      `export CRAWLERAI_MCP_TRANSPORT='stdio'`,
    );
    expect(mcpLoopbackCommand(apiBaseUrl, apiKey, 'bash')).toContain(
      `export CRAWLERAI_MCP_HOST='127.0.0.1'`,
    );
    expect(restRequestCommand(apiBaseUrl, apiKey, 'bash')).toBe(
      `curl -H 'Authorization: Bearer test'"'"'value' 'https://api.example.test/o'"'"'hare/api/v1/capabilities'`,
    );
    expect(restExtractCommand(apiBaseUrl, apiKey, 'bash')).toContain(
      `--data-raw '{"url":"https://example.com/product","surface":"ecommerce","fields":["title","price"]}'`,
    );
  });

  it('creates, verifies, reveals once, and copies an API key', async () => {
    renderPage();
    expect(await screen.findByText('Production MCP')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Key name*'), { target: { value: ' Local MCP ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }));

    expect(await screen.findByText(CREATED_KEY.api_key)).toBeInTheDocument();
    expect(apiMock.createKey.mock.calls[0]?.[0]).toBe('Local MCP');
    await waitFor(() => expect(apiMock.getCapabilities).toHaveBeenCalledWith(CREATED_KEY.api_key));
    expect(await screen.findByText(/API verified.*extract_product/)).toBeInTheDocument();
    expect(screen.getByText(/Public hosted MCP is not supported/)).toBeInTheDocument();

    // Scoped to the reveal panel: the persistent "Connect a client" card
    // renders the same commands with a placeholder key and its own tabs.
    const setup = screen.getByText('Save this key now').closest('div.space-y-4') as HTMLElement;
    expect(setup).not.toBeNull();

    // Platform is selected explicitly so the assertion does not depend on the
    // default detected from whatever machine runs the suite.
    fireEvent.click(within(setup).getByRole('button', { name: 'Windows' }));
    expect(within(setup).getByText(/curl\.exe -H/)).toBeInTheDocument();

    fireEvent.click(within(setup).getByRole('button', { name: 'macOS & Linux' }));
    expect(within(setup).getByText(/curl -H/)).toBeInTheDocument();
    expect(within(setup).getAllByText(/export CRAWLERAI_API_KEY/)).toHaveLength(2);

    fireEvent.click(within(setup).getAllByRole('button', { name: 'Copy' })[0]);
    expect(clipboardWrite).toHaveBeenCalledWith(CREATED_KEY.api_key);
  });

  it('requires confirmation before deleting a key', async () => {
    renderPage();
    expect(await screen.findByText('Production MCP')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete API key?' });
    expect(dialog).toHaveTextContent('Production MCP');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete key' }));

    await waitFor(() => expect(apiMock.deleteKey).toHaveBeenCalled());
    expect(apiMock.deleteKey.mock.calls[0]?.[0]).toBe(ACTIVE_KEY.id);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
