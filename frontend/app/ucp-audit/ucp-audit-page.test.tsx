import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TopBarProvider, useTopBarHeader } from '../../components/layout/top-bar-context';
import UcpAuditPage from './ucp-audit-page';
import { useUcpAudit } from './use-ucp-audit';

vi.mock('next/navigation', () => ({
  usePathname: () => '/ucp-audit',
}));

const apiMock = vi.hoisted(() => ({
  createUcpAuditJob: vi.fn(),
  exportUcpAuditJson: vi.fn((jobId: number) => `/api/ucp-audit/jobs/${jobId}/export.json`),
  exportUcpAuditMarkdown: vi.fn((jobId: number) => `/api/ucp-audit/jobs/${jobId}/export.md`),
  getUcpAuditJob: vi.fn(),
  listUcpAuditJobs: vi.fn(),
}));

vi.mock('../../lib/api', () => ({
  api: apiMock,
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <UcpAuditHarness />
    </QueryClientProvider>,
  );
}

function renderShellPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <TopBarProvider>
        <HeaderActions />
        <UcpAuditPage />
      </TopBarProvider>
    </QueryClientProvider>,
  );
}

function HeaderActions() {
  const header = useTopBarHeader();
  return <>{header?.actions ?? null}</>;
}

function UcpAuditHarness() {
  const controller = useUcpAudit();
  return (
    <>
      {controller.error ? <div>{controller.error}</div> : null}
      <label>
        Domain
        <input
          value={controller.domain}
          onChange={(event) => controller.setDomain(event.target.value)}
        />
      </label>
      <button type="button" onClick={controller.startAudit}>
        Start Audit
      </button>
    </>
  );
}

describe('UcpAuditPage', () => {
  beforeEach(() => {
    apiMock.createUcpAuditJob.mockReset();
    apiMock.getUcpAuditJob.mockReset();
    apiMock.listUcpAuditJobs.mockReset();
    apiMock.createUcpAuditJob.mockResolvedValue({
      id: 101,
      user_id: 1,
      domain: 'dashingdiva.com',
      status: 'queued',
      options: {},
      summary: {},
      created_at: new Date('2026-05-18T00:00:00Z').toISOString(),
      updated_at: new Date('2026-05-18T00:00:00Z').toISOString(),
      completed_at: null,
    });
    apiMock.listUcpAuditJobs.mockResolvedValue([]);
  });

  it('clears the required-domain error when a domain is entered', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /start audit/i }));

    expect(await screen.findByText('Domain is required.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/domain/i), {
      target: { value: 'https://dashingdiva.com' },
    });

    await waitFor(() => {
      expect(screen.queryByText('Domain is required.')).not.toBeInTheDocument();
    });
  });

  it('uses the current domain from the shell start button', async () => {
    renderShellPage();

    fireEvent.change(screen.getByLabelText(/domain/i), {
      target: { value: 'https://dashingdiva.com' },
    });
    const startButtons = await screen.findAllByRole('button', { name: /start audit/i });
    fireEvent.click(startButtons[0]);

    await waitFor(() => {
      expect(apiMock.createUcpAuditJob).toHaveBeenCalledWith({
        domain: 'https://dashingdiva.com',
        options: {
          sample_size: 5,
          include_agent_delta: false,
          llm_enabled: false,
          report_formats: ['json', 'markdown'],
        },
      });
    });
    expect(screen.queryByText('Domain is required.')).not.toBeInTheDocument();
  });
});
