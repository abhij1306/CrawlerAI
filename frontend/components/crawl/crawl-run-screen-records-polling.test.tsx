import {
  apiMock,
  makeRecord,
  registerCrawlRunScreenTestLifecycle,
  renderRunScreen,
  renderRunScreenWithClient,
  routeMock,
  runningRun,
  terminalRun,
} from './crawl-run-screen.test-support';
import { QueryClient } from '@tanstack/react-query';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vite-plus/test';
import { queryKeys } from '@/api/query-keys';
import type { CrawlRecord, CrawlRun } from '../../lib/api/types';
import { POLLING_INTERVALS } from '../../lib/constants/timing';

describe('CrawlRunScreen', () => {
  registerCrawlRunScreenTestLifecycle();

  it('renders completed summary chips from persisted backend values', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      result_summary: {
        extraction_verdict: 'success',
        record_count: 2,
        duration_ms: 65_000,
        quality_summary: {
          level: 'high',
        },
      },
    });
    apiMock.getRecords.mockResolvedValue({
      items: [],
      meta: { page: 1, limit: 100, total: 0 },
    });

    renderRunScreen();

    expect(await screen.findByText('1m 5s')).toBeInTheDocument();
    expect(screen.getByText('success')).toBeInTheDocument();
    expect(screen.getByText('high')).toBeInTheDocument();
  });

  it('keeps completed runs in the terminal workspace even without records', async () => {
    apiMock.getRecords.mockResolvedValue({
      items: [],
      meta: { page: 1, limit: 100, total: 0 },
    });

    renderRunScreen();

    expect(await screen.findByRole('button', { name: 'Excel (CSV)' })).toBeInTheDocument();
  });

  it('keeps the live workspace visible when summary counts are zero', async () => {
    apiMock.getCrawl.mockResolvedValue(runningRun(101));
    apiMock.getRecords.mockResolvedValue({
      items: [makeRecord(1), makeRecord(2)],
      meta: { page: 1, limit: 100, total: 2 },
    });

    renderRunScreen();

    await screen.findByText('Live Log Stream');
    expect(screen.getByRole('button', { name: 'Hard Kill' })).toBeInTheDocument();
    expect(screen.getByText('activity_stream.log')).toBeInTheDocument();
  });

  it('supports progressive table loading for large result sets', async () => {
    apiMock.getRecords.mockImplementation(
      (_runId: number, params?: { page?: number; limit?: number }) => {
        const page = Math.max(1, params?.page ?? 1);
        const limit = params?.limit ?? 100;
        const total = 150;
        const start = (page - 1) * limit;
        const count = Math.max(0, Math.min(limit, total - start));
        return Promise.resolve({
          items: Array.from({ length: count }, (_, index) => makeRecord(start + index + 1)),
          meta: { page, limit, total },
        });
      },
    );

    renderRunScreen();
    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 100 },
        { signal: expect.any(AbortSignal) },
      );
    });

    const loadMoreButton = await screen.findByRole('button', { name: 'Load More' });
    fireEvent.click(loadMoreButton);

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 2, limit: 100 },
        { signal: expect.any(AbortSignal) },
      );
    });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Load More' })).not.toBeInTheDocument();
    });
  });

  it('shows recoverable panel refresh errors when records polling fails', async () => {
    apiMock.getRecords.mockRejectedValue(new Error('records fetch failed'));

    renderRunScreen();

    expect(await screen.findByText('Some live panels failed to refresh')).toBeInTheDocument();
    expect(
      await screen.findByText(
        (content) =>
          content.includes('Unable to refresh records') &&
          content.includes('Refresh failed. Retry to restore current data.'),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/records fetch failed/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry failed panels' })).toBeInTheDocument();
  });

  it('starts loading table records before run detail resolves', async () => {
    let resolveRun!: (run: CrawlRun) => void;
    apiMock.getCrawl.mockReturnValue(
      new Promise<CrawlRun>((resolve) => {
        resolveRun = resolve;
      }),
    );

    renderRunScreen();

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 100 },
        { signal: expect.any(AbortSignal) },
      );
    });
    expect(apiMock.getDomainRecipe).not.toHaveBeenCalled();

    await act(async () => {
      resolveRun(terminalRun(101));
    });
    expect(await screen.findByRole('button', { name: /Table \(2\)/ })).toBeInTheDocument();
  });

  it('waits for run detail before loading a direct JSON route', async () => {
    routeMock.searchParams = 'run_id=42&output=json';
    let resolveRun!: (run: CrawlRun) => void;
    apiMock.getCrawl.mockReturnValue(
      new Promise<CrawlRun>((resolve) => {
        resolveRun = resolve;
      }),
    );

    renderRunScreen();

    expect(await screen.findByText('Loading Crawl')).toBeInTheDocument();
    expect(apiMock.getRecords).not.toHaveBeenCalled();

    await act(async () => {
      resolveRun(terminalRun(101));
    });

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 25 },
        { signal: expect.any(AbortSignal) },
      );
    });
    expect(await screen.findByText(/"title": "Item 1"/)).toBeInTheDocument();
  });

  it('polls only JSON records for live runs when the JSON tab is visible', async () => {
    routeMock.searchParams = 'run_id=42&output=json';
    apiMock.getCrawl.mockResolvedValue(runningRun(101));

    renderRunScreen();

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 25 },
        { signal: expect.any(AbortSignal) },
      );
    });
    expect(apiMock.getRecords).not.toHaveBeenCalledWith(
      101,
      { page: 1, limit: 100 },
      { signal: expect.any(AbortSignal) },
    );
  });

  it('refetches table records on mount even if the cache contains a fresh empty page', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 60_000,
        },
      },
    });

    queryClient.setQueryData(queryKeys.runs.detail(101), terminalRun(101));
    queryClient.setQueryData(queryKeys.runs.tableRecords(101, 100), {
      pages: [{ items: [], meta: { page: 1, limit: 100, total: 0 } }],
      pageParams: [1],
    });

    apiMock.getRecords.mockResolvedValue({
      items: [makeRecord(1), makeRecord(2)],
      meta: { page: 1, limit: 100, total: 2 },
    });

    renderRunScreenWithClient(queryClient);

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 100 },
        { signal: expect.any(AbortSignal) },
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Item 1')).toBeInTheDocument();
    });
  });

  it('does not start terminal record sync while the initial table fetch is in flight', async () => {
    let resolveRecords!: (records: {
      items: CrawlRecord[];
      meta: { page: number; limit: number; total: number };
    }) => void;
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      result_summary: {
        extraction_verdict: 'success',
        record_count: 2,
      },
    });
    apiMock.getRecords.mockReturnValue(
      new Promise((resolve) => {
        resolveRecords = resolve;
      }),
    );

    renderRunScreen();

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      await Promise.resolve();
    });
    expect(apiMock.getRecords).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRecords({ items: [], meta: { page: 1, limit: 100, total: 0 } });
    });

    await waitFor(() => {
      expect(apiMock.getRecords.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it('starts terminal record sync after a failed initial table fetch', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      result_summary: {
        extraction_verdict: 'success',
        record_count: 2,
      },
    });
    apiMock.getRecords
      .mockRejectedValueOnce(new Error('records temporarily unavailable'))
      .mockResolvedValue({
        items: [makeRecord(1), makeRecord(2)],
        meta: { page: 1, limit: 100, total: 2 },
      });

    renderRunScreen();

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(apiMock.getRecords.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    expect(await screen.findByText('Item 1')).toBeInTheDocument();
  });

  it('keeps cached latest-run table rows visible when reopening from history', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 60_000,
        },
      },
    });

    const cachedRows = {
      items: [makeRecord(1), makeRecord(2)],
      meta: { page: 1, limit: 100, total: 2 },
    };

    queryClient.setQueryData(queryKeys.runs.detail(101), terminalRun(101));
    queryClient.setQueryData(queryKeys.runs.tableRecords(101, 100), {
      pages: [cachedRows],
      pageParams: [1],
    });

    apiMock.getRecords.mockResolvedValue(cachedRows);

    renderRunScreenWithClient(queryClient);

    expect(await screen.findByText('Item 1')).toBeInTheDocument();
    expect(apiMock.getCrawl).not.toHaveBeenCalled();
    expect(apiMock.getRecords).not.toHaveBeenCalled();
  });

  it('refetches recent completed runs when summary records are present but the first table fetch is empty', async () => {
    const completedAt = new Date().toISOString();
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      updated_at: completedAt,
      completed_at: completedAt,
      result_summary: {
        extraction_verdict: 'success',
        record_count: 2,
      },
    });

    let callCount = 0;
    apiMock.getRecords.mockImplementation(
      (_runId: number, params?: { page?: number; limit?: number }) => {
        callCount += 1;
        const limit = params?.limit ?? 100;
        if (callCount === 1) {
          return Promise.resolve({
            items: [],
            meta: { page: 1, limit, total: 0 },
          });
        }
        return Promise.resolve({
          items: [makeRecord(1), makeRecord(2)],
          meta: { page: 1, limit, total: 2 },
        });
      },
    );

    renderRunScreen();

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 100 },
        { signal: expect.any(AbortSignal) },
      );
    });

    await new Promise((resolve) => window.setTimeout(resolve, POLLING_INTERVALS.RECORDS_MS + 100));

    await waitFor(() => {
      expect(apiMock.getRecords.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    await waitFor(() => {
      expect(screen.getByText('Item 1')).toBeInTheDocument();
    });
  });

  it('retries table records without preloading inactive JSON records', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      updated_at: '2026-04-08T10:05:00Z',
      completed_at: '2026-04-08T10:05:00Z',
      result_summary: {
        extraction_verdict: 'success',
        record_count: 2,
      },
    });

    let tableCalls = 0;
    let jsonCalls = 0;
    apiMock.getRecords.mockImplementation(
      (_runId: number, params?: { page?: number; limit?: number }) => {
        const limit = params?.limit ?? 100;
        if (limit === 100) {
          tableCalls += 1;
          return tableCalls === 1
            ? { items: [], meta: { page: 1, limit, total: 0 } }
            : { items: [makeRecord(1), makeRecord(2)], meta: { page: 1, limit, total: 2 } };
        }
        jsonCalls += 1;
        return jsonCalls === 1
          ? { items: [], meta: { page: 1, limit, total: 0 } }
          : { items: [makeRecord(1), makeRecord(2)], meta: { page: 1, limit, total: 2 } };
      },
    );

    renderRunScreen();

    await waitFor(() => {
      expect(tableCalls).toBeGreaterThanOrEqual(2);
    });
    expect(jsonCalls).toBe(0);
  });

  it('reconciles older completed runs when the first table fetch is empty but records are expected', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      updated_at: '2026-04-08T10:05:00Z',
      completed_at: '2026-04-08T10:05:00Z',
      result_summary: {
        extraction_verdict: 'success',
        record_count: 2,
      },
    });

    let callCount = 0;
    apiMock.getRecords.mockImplementation(
      (_runId: number, params?: { page?: number; limit?: number }) => {
        callCount += 1;
        const limit = params?.limit ?? 100;
        if (callCount === 1) {
          return Promise.resolve({
            items: [],
            meta: { page: 1, limit, total: 0 },
          });
        }
        return Promise.resolve({
          items: [makeRecord(1), makeRecord(2)],
          meta: { page: 1, limit, total: 2 },
        });
      },
    );

    renderRunScreen();

    await waitFor(() => {
      expect(apiMock.getRecords).toHaveBeenCalledWith(
        101,
        { page: 1, limit: 100 },
        { signal: expect.any(AbortSignal) },
      );
    });

    await new Promise((resolve) => window.setTimeout(resolve, POLLING_INTERVALS.RECORDS_MS + 100));

    await waitFor(() => {
      expect(apiMock.getRecords.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    await waitFor(() => {
      expect(screen.getByText('Item 1')).toBeInTheDocument();
    });
  });

  it('renders decoded Thai URLs in the JSON preview without changing the underlying records payload', async () => {
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          data: {
            title: 'Item 1',
            url: 'https://www.shop.ving.run/product/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3',
          },
        },
      ],
      meta: { page: 1, limit: 400, total: 1 },
    });

    renderRunScreen();

    const jsonButtons = await screen.findAllByRole('button', { name: 'JSON' });
    fireEvent.click(jsonButtons.at(-1)!);

    await waitFor(() => {
      expect(screen.getAllByText(/https:\/\/www\.shop\.ving\.run\/product\/สีดำ/)).not.toHaveLength(
        0,
      );
    });

    expect(screen.queryByText(/%E0%B8%AA%E0%B8%B5%E0%B8%94%E0%B8%B3/)).not.toBeInTheDocument();
  });
});
