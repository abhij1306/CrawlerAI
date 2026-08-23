import {
  apiMock,
  makeDomainRecipe,
  registerCrawlRunScreenTestLifecycle,
  renderRunScreen,
  terminalRun,
} from './crawl-run-screen.test-support';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vite-plus/test';

describe('CrawlRunScreen', () => {
  registerCrawlRunScreenTestLifecycle();

  it('renders completed-run learning tab without run-config tab', async () => {
    renderRunScreen();

    expect(await screen.findByRole('button', { name: 'Learning' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run Config' })).not.toBeInTheDocument();
    expect(apiMock.getDomainRecipe).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Learning' }));
    expect(await screen.findByRole('heading', { name: 'Run Learning' })).toBeInTheDocument();
    expect(
      (await screen.findAllByRole('button', { name: 'Activate correction' })).length,
    ).toBeGreaterThan(0);
  });

  it('renders learning as XPath winners without extracted values', async () => {
    apiMock.getDomainRecipe.mockResolvedValue({
      ...makeDomainRecipe(),
      field_learning: [
        {
          field_name: 'variant_axes',
          value: { Size: ['S', 'M'] },
          source_labels: ['dom_selector'],
          selector_kind: 'xpath',
          selector_value: "//select[@name='size']",
          source_record_ids: [1],
          representative_url_result_ids: [],
          feedback: null,
        },
      ],
    });

    renderRunScreen();

    fireEvent.click(await screen.findByRole('button', { name: 'Learning' }));
    expect(await screen.findByText(/XPath winner/)).toBeInTheDocument();
    expect(screen.queryByText(/Value:/)).not.toBeInTheDocument();
  });

  it('activates a grounded field correction from the completed-run panel', async () => {
    renderRunScreen();

    fireEvent.click(await screen.findByRole('button', { name: 'Learning' }));
    expect(await screen.findByRole('heading', { name: 'Run Learning' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Activate correction' }));

    await waitFor(() => {
      expect(apiMock.saveGroundedCorrection).toHaveBeenCalledWith(101, {
        activate: true,
        representative_url_result_ids: [11],
        labels: [
          {
            target_kind: 'field',
            subject_id: 'run:101:field:price',
            record_id: '1',
            field_name: 'price',
            canonical_value: 'Rs. 999',
            semantic_role: 'observed_field_value',
            locale_interpretation: 'as_rendered',
            grounding: [
              {
                kind: 'node',
                artifact_id: 'url-result:11:page.html',
                locator: 'css:.price',
              },
            ],
          },
        ],
      });
    });
  });

  it('hides learning for batch runs', async () => {
    apiMock.getCrawl.mockResolvedValue({
      ...terminalRun(101),
      run_type: 'batch',
    });

    renderRunScreen();

    expect(await screen.findByRole('button', { name: /Table \(2\)/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Learning' })).not.toBeInTheDocument();
    expect(apiMock.getDomainRecipe).not.toHaveBeenCalled();
  });
});
