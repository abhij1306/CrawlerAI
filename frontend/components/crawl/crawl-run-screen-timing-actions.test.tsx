import {
  apiMock,
  makeLog,
  makeRecord,
  pushMock,
  registerCrawlRunScreenTestLifecycle,
  renderRunScreen,
  terminalRun,
} from './crawl-run-screen.test-support';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vite-plus/test';
import { LogTerminal } from './log-terminal';

describe('CrawlRunScreen', () => {
  registerCrawlRunScreenTestLifecycle();

  it('stops a serial URL timer when the next URL starts', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-08T10:00:10Z'));

    render(
      <LogTerminal
        live
        logs={[
          makeLog(1, 'Starting crawl run for https://example.com/p/1 (1/2)'),
          {
            ...makeLog(2, 'Starting crawl run for https://example.com/p/2 (2/2)'),
            created_at: new Date('2026-04-08T10:00:06Z').toISOString(),
          },
        ]}
      />,
    );
    expect(screen.getByText('0m 6s')).toBeInTheDocument();
    expect(screen.getByText('0m 4s')).toBeInTheDocument();
  });

  it('ticks duration for every active parallel site group', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-08T10:00:10Z'));

    render(
      <LogTerminal
        live
        logs={[
          makeLog(1, '[url:https://example.com/p/1] Acquiring page'),
          makeLog(2, '[url:https://example.com/p/2] Acquiring page'),
        ]}
      />,
    );

    expect(screen.getAllByText('0m 10s')).toHaveLength(2);
  });

  it('prefills batch crawl with the originating jobs domain from listing runs', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      surface: 'job_listing',
      url: 'https://example.com/careers',
      settings: { crawl_module: 'category', crawl_mode: 'single' },
    });
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          source_url: 'https://jobs.example.com/posting/1',
          data: { title: 'Role 1', url: 'https://jobs.example.com/posting/1' },
        },
      ],
      meta: { page: 1, limit: 100, total: 1 },
    });

    renderRunScreen();

    const batchButton = await screen.findByRole('button', { name: 'Batch Crawl (1)' });
    fireEvent.click(batchButton);

    expect(pushMock).toHaveBeenCalledWith('/crawl?module=pdp&mode=batch');
    expect(window.sessionStorage.getItem('bulk-crawl-prefill-v1')).toBe(
      JSON.stringify({
        domain: 'jobs',
        urls: ['https://jobs.example.com/posting/1'],
      }),
    );
  });

  it('keeps batch crawl result URLs available after switching from table to logs', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      surface: 'ecommerce_listing',
      url: 'https://www.karenmillen.com/categories/womens-dresses',
      settings: { crawl_module: 'category', crawl_mode: 'single' },
      result_summary: {
        extraction_verdict: 'partial',
        record_count: 2,
      },
    });
    apiMock.getRecords.mockImplementation(
      (_runId: number, params?: { page?: number; limit?: number }) => {
        const limit = params?.limit ?? 100;
        return Promise.resolve({
          items: [
            {
              ...makeRecord(1),
              source_url: 'https://www.karenmillen.com/p/1',
              data: { title: 'Dress 1', url: 'https://www.karenmillen.com/p/1' },
            },
            {
              ...makeRecord(2),
              source_url: 'https://www.karenmillen.com/p/2',
              data: { title: 'Dress 2', url: 'https://www.karenmillen.com/p/2' },
            },
          ],
          meta: { page: 1, limit, total: 2 },
        });
      },
    );

    renderRunScreen();

    const logsTab = await screen.findByRole('button', { name: 'Logs' });
    fireEvent.click(logsTab);

    const batchButton = await screen.findByRole('button', { name: 'Batch Crawl (2)' });
    fireEvent.click(batchButton);

    expect(pushMock).toHaveBeenCalledWith('/crawl?module=pdp&mode=batch');
    expect(window.sessionStorage.getItem('bulk-crawl-prefill-v1')).toBe(
      JSON.stringify({
        domain: 'commerce',
        urls: ['https://www.karenmillen.com/p/1', 'https://www.karenmillen.com/p/2'],
      }),
    );
  });

  it('triggers direct CSV export downloads from the terminal workspace', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    try {
      renderRunScreen();

      const button = await screen.findByRole('button', { name: 'Excel (CSV)' });
      fireEvent.click(button);

      expect(apiMock.exportCsv).toHaveBeenCalledWith(101);
      expect(clickSpy).toHaveBeenCalledTimes(1);
    } finally {
      clickSpy.mockRestore();
    }
  });

  it('keeps table and exports visible for failed terminal runs with records', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      status: 'failed',
      result_summary: {
        extraction_verdict: 'partial',
        record_count: 2,
        error: 'One URL failed.',
      },
    });

    renderRunScreen();

    expect(await screen.findByRole('button', { name: /Table \(2\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Excel (CSV)' })).toBeInTheDocument();
  });
});
