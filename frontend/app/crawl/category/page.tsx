import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Category Crawl',
  description: 'Crawl and extract structured records from a category listing.',
};

// Next.js App Router entrypoint for `/crawl/category`; invoked by file-system routing.
export default function CategoryCrawlPage() {
  redirect('/crawl?module=category&mode=single');
}
