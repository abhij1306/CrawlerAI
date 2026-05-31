import type { Metadata } from 'next';

import MonitorDetailPage from './page-view';

export const metadata: Metadata = {
  title: 'Monitor Detail',
  description: 'View monitor events, history, and current snapshot.',
};

export default function MonitorDetailRoute({
  params,
}: Readonly<{
  params: Promise<{ id: string }> | { id: string };
}>) {
  return <MonitorDetailPage params={params} />;
}
