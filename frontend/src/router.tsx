import { lazy, Suspense } from 'react';
import type { JSX } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';

import LoginPage from '../app/login/page-view';
import RegisterPage from '../app/register/page-view';
import CrawlPage from '../app/crawl/page-view';
import DashboardPage from '../app/dashboard/page-view';
import { AppShell } from '../components/layout/app-shell';
import { QueryProvider } from '../components/ui/query-provider';

const AdminLlmPage = lazy(() => import('../app/admin/llm/page-view'));
const AdminUsersPage = lazy(() => import('../app/admin/users/page-view'));
const DataEnrichmentPage = lazy(() => import('../app/data-enrichment/page-view'));
const JobsPage = lazy(() => import('../app/jobs/page-view'));
const ProductIntelligencePage = lazy(() => import('../app/product-intelligence/page-view'));
const RunTracePage = lazy(() => import('../app/run-trace/page-view'));
const RunsPage = lazy(() => import('../app/runs/page-view'));
const SelectorsPage = lazy(() => import('../app/selectors/page-view'));
const DomainMemoryPage = lazy(() => import('../app/domain-memory/page-view'));

function RunDetailRedirect() {
  const params = useParams();
  return <Navigate to={`/crawl?run_id=${encodeURIComponent(params.run_id ?? '')}`} replace />;
}

function CrawlModeRedirect({ module, mode }: Readonly<{ module: string; mode?: string }>) {
  const search = new URLSearchParams({ module });
  if (mode) {
    search.set('mode', mode);
  }
  return <Navigate to={`/crawl?${search.toString()}`} replace />;
}

function RouteFallback() {
  return (
    <main className="app-page-frame">
      <div className="app-page-inner page-stack-lg" aria-busy="true">
        <div className="skeleton h-8 w-56 rounded-md" />
        <div className="skeleton h-72 w-full rounded-lg" />
      </div>
    </main>
  );
}

function lazyElement(element: JSX.Element) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

export function ViteApp() {
  return (
    <BrowserRouter>
      <QueryProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/crawl" element={<CrawlPage />} />
            <Route
              path="/crawl/category"
              element={<CrawlModeRedirect module="category" mode="category" />}
            />
            <Route path="/crawl/pdp" element={<CrawlModeRedirect module="pdp" mode="single" />} />
            <Route path="/crawl/bulk" element={<CrawlModeRedirect module="pdp" mode="bulk" />} />
            <Route path="/runs" element={lazyElement(<RunsPage />)} />
            <Route path="/runs/:run_id" element={<RunDetailRedirect />} />
            <Route path="/jobs" element={lazyElement(<JobsPage />)} />
            <Route path="/selectors" element={lazyElement(<SelectorsPage />)} />
            <Route path="/domain-memory" element={lazyElement(<DomainMemoryPage />)} />
            <Route path="/admin/users" element={lazyElement(<AdminUsersPage />)} />
            <Route path="/admin/llm" element={lazyElement(<AdminLlmPage />)} />
            <Route path="/data-enrichment" element={lazyElement(<DataEnrichmentPage />)} />
            <Route
              path="/product-intelligence"
              element={lazyElement(<ProductIntelligencePage />)}
            />
            <Route path="/run-trace" element={lazyElement(<RunTracePage />)} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AppShell>
      </QueryProvider>
    </BrowserRouter>
  );
}
