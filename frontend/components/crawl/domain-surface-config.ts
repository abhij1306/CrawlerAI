import type { CrawlDomain, CrawlSurface } from '../../lib/api/types';

export type DomainCrawlTab = 'category' | 'pdp';

export const DOMAIN_OPTIONS: Array<{ value: CrawlDomain; label: string }> = [
  { value: 'content', label: 'Content' },
  { value: 'commerce', label: 'Commerce' },
  { value: 'jobs', label: 'Jobs' },
  { value: 'automobiles', label: 'Automobiles' },
  { value: 'article', label: 'Article' },
  { value: 'forum_thread', label: 'Forum Thread' },
];

export const DOMAIN_TABS: Record<CrawlDomain, Array<{ value: DomainCrawlTab; label: string }>> = {
  content: [
    { value: 'category', label: 'Rows From Page' },
    { value: 'pdp', label: 'Page Content' },
  ],
  commerce: [
    { value: 'category', label: 'Category Crawl' },
    { value: 'pdp', label: 'PDP Crawl' },
  ],
  jobs: [
    { value: 'category', label: 'Jobs Listing' },
    { value: 'pdp', label: 'Job Detail' },
  ],
  automobiles: [
    { value: 'category', label: 'Listings' },
    { value: 'pdp', label: 'Detail' },
  ],
  article: [
    { value: 'category', label: 'Article Feed' },
    { value: 'pdp', label: 'Article Page' },
  ],
  forum_thread: [{ value: 'pdp', label: 'Forum Thread' }],
};

type SurfaceDispatchKey = `${Exclude<CrawlDomain, 'forum_thread'>}:${DomainCrawlTab}` | 'forum_thread:pdp';

export const SURFACE_DISPATCH: Record<SurfaceDispatchKey, CrawlSurface> = {
  'content:category': 'content_listing',
  'content:pdp': 'content_detail',
  'commerce:category': 'ecommerce_listing',
  'commerce:pdp': 'ecommerce_detail',
  'jobs:category': 'job_listing',
  'jobs:pdp': 'job_detail',
  'automobiles:category': 'automobile_listing',
  'automobiles:pdp': 'automobile_detail',
  'article:category': 'article_listing',
  'article:pdp': 'article_detail',
  'forum_thread:pdp': 'forum_detail',
};

export const DEFAULT_FIELDS: Record<CrawlSurface, string[]> = {
  content_detail: ['title', 'content', 'url'],
  content_listing: ['title', 'url'],
  ecommerce_listing: ['title', 'price', 'image_url', 'url'],
  ecommerce_detail: ['title', 'price', 'brand', 'sku', 'availability', 'image_url'],
  job_listing: ['title', 'company', 'location', 'url'],
  job_detail: ['title', 'company', 'location', 'salary', 'apply_url'],
  automobile_listing: ['title', 'price', 'url', 'image_url', 'make', 'model', 'year'],
  automobile_detail: ['title', 'price', 'make', 'model', 'year', 'mileage', 'url'],
  article_listing: ['title', 'publication_date', 'author', 'url'],
  article_detail: ['title', 'author', 'publication_date', 'content', 'url'],
  forum_detail: ['title', 'author', 'content', 'reply_count', 'view_count', 'url'],
};
