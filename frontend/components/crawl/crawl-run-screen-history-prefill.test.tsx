import {
  apiMock,
  makeDomainRecipe,
  makeRecord,
  pushMock,
  registerCrawlRunScreenTestLifecycle,
  renderRunScreen,
  terminalRun,
} from './crawl-run-screen.test-support';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vite-plus/test';
import { storeProductIntelligencePrefill } from '../../lib/crawl/prefill';

describe('CrawlRunScreen', () => {
  registerCrawlRunScreenTestLifecycle();

  it('loads run history only after the history drawer opens', async () => {
    renderRunScreen();

    await screen.findByRole('button', { name: /Table \(2\)/ });
    expect(apiMock.listCrawls).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    await waitFor(() => {
      expect(apiMock.listCrawls).toHaveBeenCalledWith(
        { limit: 20 },
        { signal: expect.any(AbortSignal) },
      );
    });
  });

  it('prefills Product Intelligence from selected listing records', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      surface: 'ecommerce_listing',
      url: 'https://www.belk.com/category',
      settings: { crawl_module: 'category', crawl_mode: 'single' },
    });
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          source_url: 'https://www.belk.com/p/1',
          data: {
            brand: "Levi's",
            title: '511 Jeans',
            price: '$59.99',
            url: 'https://www.belk.com/p/1',
          },
        },
      ],
      meta: { page: 1, limit: 100, total: 1 },
    });

    renderRunScreen();

    const productButton = await screen.findByRole(
      'button',
      { name: 'Product Intelligence (1)' },
      { timeout: 5000 },
    );
    fireEvent.click(productButton);

    expect(pushMock).toHaveBeenCalledWith('/product-intelligence');
    expect(
      JSON.parse(window.sessionStorage.getItem('product-intelligence-prefill-v1') || '{}'),
    ).toEqual({
      source_run_id: 101,
      source_domain: 'https://www.belk.com/category',
      records: [
        {
          id: 1,
          run_id: 101,
          source_url: 'https://www.belk.com/p/1',
          data: {
            brand: "Levi's",
            title: '511 Jeans',
            price: '$59.99',
            url: 'https://www.belk.com/p/1',
          },
        },
      ],
    });
  });

  it('prefills Product Intelligence from selected detail records', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      surface: 'ecommerce_detail',
      url: 'https://www.belk.com/p/levi-s-511-slim-fit-stretch-jeans/32009271204401.html',
      settings: { crawl_module: 'pdp', crawl_mode: 'single' },
    });
    apiMock.getRecords.mockResolvedValue({
      items: [
        {
          ...makeRecord(1),
          source_url:
            'https://www.belk.com/p/levi-s-511-slim-fit-stretch-jeans/32009271204401.html',
          data: {
            brand: "Levi's",
            title: '511 Slim Fit Stretch Jeans',
            price: '$59.99',
            sku_upc: '00194500874886',
            barcode: '00194500874886',
            product_id: '32009271204401',
            url: 'https://www.belk.com/p/levi-s-511-slim-fit-stretch-jeans/32009271204401.html',
          },
        },
      ],
      meta: { page: 1, limit: 100, total: 1 },
    });

    renderRunScreen();

    const productButton = await screen.findByRole(
      'button',
      { name: 'Product Intelligence (1)' },
      { timeout: 5000 },
    );
    fireEvent.click(productButton);

    expect(pushMock).toHaveBeenCalledWith('/product-intelligence');
    expect(
      JSON.parse(window.sessionStorage.getItem('product-intelligence-prefill-v1') || '{}'),
    ).toMatchObject({
      source_run_id: 101,
      source_domain: 'https://www.belk.com/p/levi-s-511-slim-fit-stretch-jeans/32009271204401.html',
      records: [
        {
          id: 1,
          run_id: 101,
          data: {
            sku_upc: '00194500874886',
            barcode: '00194500874886',
            product_id: '32009271204401',
          },
        },
      ],
    });
  });

  it('falls back to reduced Product Intelligence prefill when session storage is full', () => {
    const stored = new Map<string, string>();
    const setItemMock = vi.fn((key: string, value: string) => {
      stored.set(key, value);
    });
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    setItemMock.mockImplementationOnce(() => {
      throw new DOMException('Quota exceeded', 'QuotaExceededError');
    });
    const storage = {
      setItem: setItemMock,
      getItem: (key: string) => stored.get(key) ?? null,
      removeItem: (key: string) => {
        stored.delete(key);
      },
    } as unknown as Storage;
    try {
      storeProductIntelligencePrefill(
        {
          source_run_id: 101,
          source_domain: 'https://www.belk.com/category',
          records: [
            {
              id: 1,
              run_id: 101,
              source_url: 'https://www.belk.com/p/1',
              data: {
                brand: "Levi's",
                title: '511 Jeans',
                price: '$59.99',
                url: 'https://www.belk.com/p/1',
              },
            },
          ],
        },
        storage,
      );

      expect(consoleSpy).toHaveBeenCalled();
      expect(JSON.parse(storage.getItem('product-intelligence-prefill-v1') || '{}')).toEqual({
        source_run_id: 101,
        source_domain: 'https://www.belk.com/category',
        records: [
          {
            id: 1,
            run_id: 101,
            source_url: 'https://www.belk.com/p/1',
            data: {},
          },
        ],
      });
    } finally {
      consoleSpy.mockRestore();
    }
  });

  it('reports when no reusable cookie state was observed for a browser run', async () => {
    apiMock.getDomainRecipe.mockResolvedValue({
      ...makeDomainRecipe(),
      acquisition_evidence: {
        ...makeDomainRecipe().acquisition_evidence,
        cookie_memory_available: false,
      },
    });

    renderRunScreen();

    const learningButtons = await screen.findAllByRole('button', { name: 'Learning' });
    fireEvent.click(learningButtons.at(-1)!);

    expect(
      await screen.findByText(/Cookie Memory: No reusable state observed/i),
    ).toBeInTheDocument();
  });
});
