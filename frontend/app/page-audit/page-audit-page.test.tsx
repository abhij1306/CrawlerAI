import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TopBarProvider, useTopBarHeader } from '../../components/layout/top-bar-context';
import PageAuditPage from './page-audit-page';

const replaceMock = vi.fn();
let queryValues: Record<string, string> = {};

vi.mock('next/navigation', () => ({
  usePathname: () => '/page-audit',
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => ({
    get: (key: string) => queryValues[key] ?? null,
  }),
}));

const apiMock = vi.hoisted(() => ({
  createPageAuditJob: vi.fn(),
  getPageAuditJob: vi.fn(),
  exportPageAuditJson: vi.fn((jobId: number) => `/api/page-audit/jobs/${jobId}/export.json`),
  exportPageAuditMarkdown: vi.fn((jobId: number) => `/api/page-audit/jobs/${jobId}/export.md`),
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
      <TopBarProvider>
        <HeaderActions />
        <PageAuditPage />
      </TopBarProvider>
    </QueryClientProvider>,
  );
}

function HeaderActions() {
  const header = useTopBarHeader();
  return <>{header?.actions ?? null}</>;
}

describe('PageAuditPage', () => {
  beforeEach(() => {
    queryValues = {};
    replaceMock.mockReset();
    apiMock.createPageAuditJob.mockReset();
    apiMock.getPageAuditJob.mockReset();
    apiMock.createPageAuditJob.mockResolvedValue({
      id: 41,
      user_id: 1,
      url: 'https://example.com/page',
      context: 'generic',
      status: 'queued',
      options: {},
      summary: {},
      created_at: '2026-06-05T00:00:00Z',
      updated_at: '2026-06-05T00:00:00Z',
      completed_at: null,
    });
  });

  it('starts a page audit for any single URL', async () => {
    queryValues = { url: 'https://example.com/page' };
    renderPage();

    fireEvent.change(screen.getByLabelText(/audit context/i), {
      target: { value: 'generic' },
    });
    fireEvent.click(screen.getByRole('button', { name: /start audit/i }));

    await waitFor(() => {
      expect(apiMock.createPageAuditJob).toHaveBeenCalledWith({
        url: 'https://example.com/page',
        context: 'generic',
      });
    });
    expect(replaceMock).toHaveBeenCalledWith('/page-audit?job_id=41');
  });

  it('renders score groups, critical failures, check groups, and exports', async () => {
    queryValues = { job_id: '41' };
    apiMock.getPageAuditJob.mockResolvedValue({
      job: {
        id: 41,
        user_id: 1,
        url: 'https://example.com/page',
        context: 'auto',
        status: 'complete',
        options: {},
        summary: {},
        created_at: '2026-06-05T00:00:00Z',
        updated_at: '2026-06-05T00:00:00Z',
        completed_at: '2026-06-05T00:01:00Z',
      },
      result: {
        id: 9,
        job_id: 41,
        url: 'https://example.com/page',
        markdown_report: '# report',
        created_at: '2026-06-05T00:01:00Z',
        updated_at: '2026-06-05T00:01:00Z',
        report_json: {
          url: 'https://example.com/page',
          scores: {
            seo: 72,
            performance_indicators: 61,
            structured_data: 50,
            accessibility: 85,
            ecommerce_readiness: null,
          },
          critical_failures: [
            {
              id: 'h1_count',
              label: 'Page has exactly one H1',
              severity: 'critical',
              data_source: 'source',
              passed: false,
              applicable: true,
              detected_value: 0,
              expected_value: 1,
              fix: 'Use exactly one H1.',
            },
          ],
          source_checks: [
            {
              id: 'h1_count',
              label: 'Page has exactly one H1',
              category: 'seo',
              severity: 'critical',
              data_source: 'source',
              passed: false,
              applicable: true,
              detected_value: 0,
              expected_value: 1,
              fix: 'Use exactly one H1.',
            },
          ],
          dom_checks: [],
          diff_checks: [],
          render_summary: { browser_engine: 'patchright' },
        },
      },
    });

    renderPage();

    expect(await screen.findByText('72')).toBeInTheDocument();
    expect(screen.getByText('Critical Failures')).toBeInTheDocument();
    expect(screen.getAllByText('Page has exactly one H1').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /^source$/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /export json/i })).toHaveAttribute(
      'href',
      '/api/page-audit/jobs/41/export.json',
    );
    expect(screen.getByRole('link', { name: /export markdown/i })).toHaveAttribute(
      'href',
      '/api/page-audit/jobs/41/export.md',
    );
  });

  it('shows the persisted failure reason for a failed audit', async () => {
    queryValues = { job_id: '41' };
    apiMock.getPageAuditJob.mockResolvedValue({
      job: {
        id: 41,
        user_id: 1,
        url: 'https://example.com/page',
        context: 'auto',
        status: 'failed',
        options: {},
        summary: { error: 'Browser render timed out' },
        created_at: '2026-06-05T00:00:00Z',
        updated_at: '2026-06-05T00:01:00Z',
        completed_at: '2026-06-05T00:01:00Z',
      },
      result: null,
    });

    renderPage();

    expect(await screen.findByText('Browser render timed out')).toBeInTheDocument();
  });
});
