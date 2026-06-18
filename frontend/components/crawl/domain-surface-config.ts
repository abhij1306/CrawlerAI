import type { CrawlDomain, CrawlSurface } from '../../lib/api/types';

export type DomainCrawlTab = 'category' | 'pdp';

export const DOMAIN_OPTIONS: Array<{ value: CrawlDomain; label: string }> = [
  { value: 'commerce', label: 'Commerce' },
  { value: 'jobs', label: 'Jobs' },
];

export const DOMAIN_TABS: Record<CrawlDomain, Array<{ value: DomainCrawlTab; label: string }>> = {
  commerce: [
    { value: 'category', label: 'Category Crawl' },
    { value: 'pdp', label: 'PDP Crawl' },
  ],
  jobs: [
    { value: 'category', label: 'Jobs Listing' },
    { value: 'pdp', label: 'Job Detail' },
  ],
};

type SurfaceDispatchKey = `${CrawlDomain}:${DomainCrawlTab}`;

export const SURFACE_DISPATCH: Record<SurfaceDispatchKey, CrawlSurface> = {
  'commerce:category': 'ecommerce_listing',
  'commerce:pdp': 'ecommerce_detail',
  'jobs:category': 'job_listing',
  'jobs:pdp': 'job_detail',
};

export const DEFAULT_FIELDS: Record<CrawlSurface, string[]> = {
  ecommerce_listing: ['title', 'price', 'image_url', 'url'],
  ecommerce_detail: ['title', 'price', 'brand', 'sku', 'availability', 'image_url'],
  job_listing: ['title', 'company', 'location', 'url'],
  job_detail: ['title', 'company', 'location', 'salary', 'apply_url'],
};
