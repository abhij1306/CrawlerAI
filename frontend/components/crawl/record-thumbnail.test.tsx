import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { CrawlRecord } from '../../lib/api/types';
import { RecordsTable } from './records-table';
import { isLikelyThumbnailUrl } from './record-thumbnail';

function recordWithImg(img: string): CrawlRecord {
  return {
    id: 1,
    run_id: 1,
    source_url: 'https://example.com/source',
    data: {
      img,
      title: 'Result',
      url: 'https://example.com/source',
    },
    raw_data: {},
    discovered_data: {},
    source_trace: {},
    raw_html_path: null,
    created_at: '2026-06-27T00:00:00Z',
  };
}

describe('record thumbnails', () => {
  it('accepts image-like CDN URLs and rejects product page URLs', () => {
    expect(isLikelyThumbnailUrl('https://media-assets.grailed.com/prd/listing/1?auto=format')).toBe(
      true,
    );
    expect(isLikelyThumbnailUrl('https://cdn.example.com/images/shoe.webp')).toBe(true);
    expect(
      isLikelyThumbnailUrl(
        'https://www.zappos.com/kratos/p/womens-hoka-bondi-9/product/9984296/color/1108576',
      ),
    ).toBe(false);
  });

  it('does not render product page URLs as table thumbnails', () => {
    render(
      <RecordsTable
        records={[
          recordWithImg(
            'https://www.zappos.com/kratos/p/womens-hoka-bondi-9/product/9984296/color/1108576',
          ),
        ]}
        visibleColumns={['img', 'title', 'url']}
        selectedIds={[]}
        onSelectAll={() => {}}
        onToggleRow={() => {}}
      />,
    );

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('--')).toBeInTheDocument();
  });
});
