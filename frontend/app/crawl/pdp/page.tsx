import { redirect } from 'next/navigation';

// Next.js App Router entrypoint for `/crawl/pdp`; invoked by file-system routing.
export default function PdpCrawlPage() {
  redirect('/crawl?module=pdp&mode=single');
}
