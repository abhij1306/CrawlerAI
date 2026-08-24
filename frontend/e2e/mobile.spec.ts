/**
 * Mobile layout regressions.
 *
 * Runs at a phone viewport (see the `mobile` project in playwright.config.ts).
 * The contract is narrow on purpose: the app must be reachable and nothing may
 * spill horizontally out of the page. Dense tables still scroll inside their
 * own container — that is by design, not a failure.
 */
import { expect, test, type Page } from '@playwright/test';

const adminUser = {
  id: 1,
  email: 'qa@example.com',
  role: 'admin',
  is_active: true,
  created_at: '2026-04-08T10:00:00Z',
  updated_at: '2026-04-08T10:00:00Z',
};

const BACKEND = 'http://127.0.0.1:8001';

const ROUTES = ['/dashboard', '/runs', '/jobs', '/api-access', '/crawl'];

async function mockApi(page: Page) {
  // Anchored to the backend origin: a bare '**/api/**' glob also matches the
  // dev server's own module URLs (lib/api/dashboard.ts), which would serve JS
  // as JSON and stop React mounting entirely.
  await page.route(`${BACKEND}/api/**`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
  await page.route(`${BACKEND}/api/dashboard**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_runs: 3,
        active_runs: 1,
        total_records: 150,
        recent_runs: [],
        top_domains: [],
      }),
    }),
  );
  await page.route(`${BACKEND}/api/auth/me**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(adminUser),
    }),
  );
}

test('navigation is reachable through the drawer', async ({ page }) => {
  await mockApi(page);
  await page.goto('/dashboard');

  // The permanent sidebar is replaced by a drawer at this width.
  await expect(page.getByRole('link', { name: 'Crawl Studio' })).toBeHidden();

  await page.getByTestId('app-nav-open').click();
  const drawerLink = page.getByRole('link', { name: 'Crawl Studio' });
  await expect(drawerLink).toBeVisible();
  await drawerLink.click();

  await expect(page).toHaveURL(/\/crawl/);
  // Navigating from inside the drawer closes it.
  await expect(page.getByRole('link', { name: 'Crawl Studio' })).toBeHidden();
});

for (const route of ROUTES) {
  test(`${route} does not overflow horizontally`, async ({ page }) => {
    await mockApi(page);
    await page.goto(route);
    await page.waitForLoadState('networkidle');

    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });
}
