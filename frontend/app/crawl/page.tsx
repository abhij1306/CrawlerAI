import type { Metadata } from 'next';
import dynamic from 'next/dynamic';

const CrawlPage = dynamic(() => import('./page-view'));

export const metadata: Metadata = {
  title: 'Crawl Studio',
  description: 'Configure and run deterministic crawls for commerce and tabular targets.',
};

export default CrawlPage;
