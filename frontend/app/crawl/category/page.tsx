import { redirect } from 'next/navigation';

// Next.js App Router entrypoint for `/crawl/category`; invoked by file-system routing.
export default function CategoryCrawlPage() {
  redirect('/crawl?module=category&mode=single');
}
