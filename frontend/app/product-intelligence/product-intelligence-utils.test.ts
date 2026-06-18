import { describe, expect, it } from 'vitest';

import type { ProductIntelligenceJobDetail } from '../../lib/api/types';
import { candidateConfidence, detailToDiscovery } from './product-intelligence-utils';

describe('product intelligence utils', () => {
  it('hydrates confidence from matches when candidate payload has no intelligence', () => {
    const detail: ProductIntelligenceJobDetail = {
      job: {
        id: 10,
        user_id: 1,
        source_run_id: 20,
        status: 'complete',
        options: {},
        summary: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        completed_at: '2026-01-01T00:00:00Z',
      },
      source_products: [
        {
          id: 30,
          job_id: 10,
          source_run_id: 20,
          source_record_id: 40,
          source_url: 'https://www.belk.com/p/source.html',
          brand: 'Nike',
          normalized_brand: 'nike',
          title: 'Run Defy Sneakers',
          sku: '',
          mpn: '',
          gtin: '',
          price: null,
          currency: '',
          image_url: '',
          is_private_label: false,
          payload: {},
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      candidates: [
        {
          id: 50,
          job_id: 10,
          source_product_id: 30,
          candidate_crawl_run_id: 60,
          url: 'https://www.nike.com/t/run-defy/HM9593',
          domain: 'nike.com',
          source_type: 'brand_dtc',
          query_used: 'nike run defy',
          search_rank: 1,
          status: 'crawl_complete',
          payload: {},
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      matches: [
        {
          id: 70,
          job_id: 10,
          source_product_id: 30,
          candidate_id: 50,
          candidate_record_id: 80,
          score: 0.72,
          score_label: 'medium',
          review_status: 'pending',
          source_price: null,
          candidate_price: null,
          currency: '',
          availability: '',
          candidate_url: 'https://www.nike.com/t/run-defy/HM9593',
          candidate_domain: 'nike.com',
          score_reasons: { brand_match: true },
          llm_enrichment: {},
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    };

    const discovery = detailToDiscovery(detail);

    const firstCandidate = discovery.candidates[0];

    expect(firstCandidate).toBeDefined();
    if (!firstCandidate) {
      throw new Error('Expected first Product Intelligence candidate');
    }
    const intelligence = firstCandidate.intelligence;
    expect(intelligence).toBeDefined();
    if (!intelligence) {
      throw new Error('Expected Product Intelligence candidate intelligence');
    }

    expect(candidateConfidence(firstCandidate)).toBe(0.72);
    expect(intelligence.score_reasons).toEqual({ brand_match: true });
  });
});
