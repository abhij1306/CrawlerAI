import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Bulk Crawl',
  description: 'Submit a batch of product URLs for structured extraction.',
};

// Next.js App Router entrypoint for `/crawl/bulk`; invoked by file-system routing.
export default function BulkCrawlPage() {
  redirect('/crawl?module=pdp&mode=batch');
}
