import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TopBarProvider, useTopBarHeader } from '../layout/top-bar-context';
import { PageAuditWorkspace } from './page-audit-workspace';

const replaceMock = vi.fn();
vi.mock('next/navigation', () => ({
  usePathname: () => '/crawl',
  useRouter: () => ({ replace: replaceMock }),
}));

const apiMock = vi.hoisted(() => ({
  getPageAuditJob: vi.fn(),
  exportPageAuditJson: vi.fn((jobId: number) => `/api/page-audit/jobs/${jobId}/export.json`),
  exportPageAuditMarkdown: vi.fn((jobId: number) => `/api/page-audit/jobs/${jobId}/export.md`),
}));

vi.mock('../../lib/api', () => ({
  api: apiMock,
}));

function renderPage(jobId = 41) {
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
        <PageAuditWorkspace jobId={jobId} />
      </TopBarProvider>
    </QueryClientProvider>,
  );
}

function HeaderActions() {
  const header = useTopBarHeader();
  return <>{header?.actions ?? null}</>;
}

describe('PageAuditWorkspace', () => {
  beforeEach(() => {
    replaceMock.mockReset();
    apiMock.getPageAuditJob.mockReset();
  });

  it('renders score groups, critical failures, check groups, and exports', async () => {
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
