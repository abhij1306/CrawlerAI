import { expect, test, type Page } from '@playwright/test';

const RESILIENCE_EXPECT_TIMEOUT_MS = 15000;

const adminUser = {
  id: 1,
  email: 'qa@example.com',
  role: 'admin',
  is_active: true,
  created_at: '2026-04-08T10:00:00Z',
  updated_at: '2026-04-08T10:00:00Z',
};

async function mockSession(page: Page, user = adminUser) {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(user),
    });
  });
}

async function mockDashboard(page: Page) {
  await page.route('**/api/dashboard', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_runs: 1,
        active_runs: 0,
        total_records: 150,
        recent_runs: [],
        top_domains: [],
      }),
    });
  });
}

test('session expiration redirects protected routes to login', async ({ page }) => {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not authenticated' }),
    });
  });

  await page.goto('/runs');
  await expect(page).toHaveURL(/\/login/);
});

test('API outage surfaces a recoverable runs error state', async ({ page }) => {
  await mockSession(page);
  let crawlRequests = 0;
  await page.route('**/api/crawls**', async (route) => {
    crawlRequests += 1;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Service unavailable' }),
    });
  });

  await page.goto('/runs');
  await expect
    .poll(() => crawlRequests, { timeout: RESILIENCE_EXPECT_TIMEOUT_MS })
    .toBeGreaterThanOrEqual(4);
  await expect(page.getByText('Unable to load run history.')).toBeVisible({
    timeout: RESILIENCE_EXPECT_TIMEOUT_MS,
  });
});

test('admin authorization failures surface on admin users page', async ({ page }) => {
  await mockSession(page);
  await page.route('**/api/users**', async (route) => {
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Forbidden' }),
    });
  });

  await page.goto('/admin/users');
  await expect(page.getByText('Forbidden')).toBeVisible({
    timeout: RESILIENCE_EXPECT_TIMEOUT_MS,
  });
});

test('major feature routes load with mocked session', async ({ page }) => {
  await mockSession(page);
  await mockDashboard(page);
  await page.route('**/api/crawls?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], meta: { page: 1, limit: 50, total: 0 } }),
    });
  });
  await page.route('**/api/data-enrichment/jobs**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });
  await page.route('**/api/product-intelligence/jobs**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });
  await page.route('**/api/knowledge/sites', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sites: [] }),
    });
  });

  for (const [path, heading] of [
    ['/runs', 'Run History'],
    ['/data-enrichment', 'Data Enrichment'],
    ['/product-intelligence', 'Product Intelligence'],
    ['/domain-memory', 'Domain Memory'],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
  }
});

test('large run record lists remain visible', async ({ page }) => {
  await mockSession(page);
  await page.route('**/api/crawls/101', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 101,
        user_id: 1,
        run_type: 'crawl',
        url: 'https://example.com/products/chair',
        status: 'completed',
        surface: 'ecommerce_detail',
        settings: {},
        requested_fields: [],
        result_summary: { extraction_verdict: 'success', record_count: 150 },
        created_at: '2026-04-08T10:00:00Z',
        updated_at: '2026-04-08T10:05:00Z',
        completed_at: '2026-04-08T10:05:00Z',
      }),
    });
  });
  await page.route('**/api/crawls/101/records**', async (route) => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get('limit') ?? 100);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: Array.from({ length: Math.min(limit, 100) }, (_, index) => ({
          id: index + 1,
          run_id: 101,
          source_url: `https://example.com/products/${index + 1}`,
          data: { title: `Item ${index + 1}`, url: `https://example.com/products/${index + 1}` },
          raw_data: {},
          discovered_data: {},
          source_trace: {},
          raw_html_path: null,
          created_at: '2026-04-08T10:00:00Z',
        })),
        meta: { page: 1, limit, total: 150 },
      }),
    });
  });
  await page.route('**/api/crawls/101/logs**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/crawl?run_id=101');
  await expect(page.getByRole('button', { name: /Table \(150\)/ })).toBeVisible();
  await expect(page.getByText('Item 1', { exact: true })).toBeVisible();
});
