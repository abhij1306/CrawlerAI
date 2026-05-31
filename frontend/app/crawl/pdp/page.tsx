import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'PDP Crawl',
  description: 'Extract structured data from a single product detail page.',
};

// Next.js App Router entrypoint for `/crawl/pdp`; invoked by file-system routing.
export default function PdpCrawlPage() {
  redirect('/crawl?module=pdp&mode=single');
}
