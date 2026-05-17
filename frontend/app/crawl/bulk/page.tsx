import { redirect } from 'next/navigation';

// Next.js App Router entrypoint for `/crawl/bulk`; invoked by file-system routing.
export default function BulkCrawlPage() {
  redirect('/crawl?module=pdp&mode=batch');
}
