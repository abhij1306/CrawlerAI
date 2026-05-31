import type { Metadata } from 'next';

import AlertDetailPage from './page-view';

export const metadata: Metadata = {
  title: 'Alert Detail',
  description: 'View alert events, history, snapshot, and webhook deliveries.',
};

export default function AlertDetailRoute({
  params,
}: Readonly<{
  params: Promise<{ id: string }> | { id: string };
}>) {
  return <AlertDetailPage params={params} />;
}
