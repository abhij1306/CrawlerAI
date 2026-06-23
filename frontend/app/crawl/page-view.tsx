import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Skeleton } from '../../components/ui/primitives';
import {
  parseRequestedCategoryMode,
  parseRequestedCrawlTab,
  parseRequestedPdpMode,
} from '../../components/crawl/shared';

const crawlScreenLoading = () => (
  <main className="mx-auto w-full max-w-[1440px] px-5 py-6 md:px-6">
    <div className="space-y-4">
      <Skeleton className="h-10 w-64 max-w-full" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <Skeleton className="h-[520px] w-full rounded-lg" />
    </div>
  </main>
);

const CrawlConfigScreen = lazy(() =>
  import('../../components/crawl/crawl-config-screen').then((module) => ({
    default: module.CrawlConfigScreen,
  })),
);
const CrawlRunScreen = lazy(() =>
  import('../../components/crawl/crawl-run-screen').then((module) => ({
    default: module.CrawlRunScreen,
  })),
);

function CrawlPageContent() {
  const [searchParams] = useSearchParams();
  const runId =
    Number(
      searchParams.get('run_id') || searchParams.get('runId') || searchParams.get('runid') || 0,
    ) || null;

  if (runId !== null) return <CrawlRunScreen key={runId} runId={runId} />;

  return (
    <CrawlConfigScreen
      requestedTab={parseRequestedCrawlTab(searchParams.get('module'))}
      requestedCategoryMode={parseRequestedCategoryMode(searchParams.get('mode'))}
      requestedPdpMode={parseRequestedPdpMode(searchParams.get('mode'))}
      requestedUrl={searchParams.get('url') ?? ''}
    />
  );
}

export default function CrawlPage() {
  return (
    <Suspense fallback={crawlScreenLoading()}>
      <CrawlPageContent />
    </Suspense>
  );
}
