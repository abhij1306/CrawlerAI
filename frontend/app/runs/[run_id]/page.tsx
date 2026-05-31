import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Run Detail',
  description: 'View crawl run details and review extracted records.',
};

/**
 * Next.js App Router entrypoint for `/runs/[run_id]`; invoked by file-system routing.
 * Legacy run detail route redirects to the crawl studio which has
 * the full two-column view and review flow.
 */
export default async function RunDetailRedirect({
  params,
}: Readonly<{
  params: Promise<{ run_id: string }> | { run_id: string };
}>) {
  const resolvedParams = await params;
  redirect(`/crawl?run_id=${encodeURIComponent(resolvedParams.run_id)}`);
}
