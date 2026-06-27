import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vite-plus/test';

import { TopBarProvider } from '../layout/top-bar-context';
import { PageHeader, RunSummaryChips } from './patterns';

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useLocation: () => ({ pathname: '/crawl', search: '', hash: '', state: null, key: 'test' }),
  };
});

describe('RunSummaryChips', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses stable semantic keys when chip values repeat', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<RunSummaryChips duration="0m 0s" verdict="unknown" quality="unknown" />);

    const duplicateKeyWarning = consoleSpy.mock.calls.some((call) =>
      call.some((entry) => String(entry).includes('Encountered two children with the same key')),
    );
    expect(duplicateKeyWarning).toBe(false);
  });
});

describe('PageHeader', () => {
  it('accepts fragment actions without crashing', () => {
    expect(() =>
      render(
        <TopBarProvider>
          <PageHeader
            title="Project"
            actions={
              <>
                <button type="button">CSV</button>
                <button type="button">Promote</button>
              </>
            }
          />
        </TopBarProvider>,
      ),
    ).not.toThrow();
  });
});
