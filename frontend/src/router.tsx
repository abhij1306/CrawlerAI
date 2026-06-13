import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';

import AdminLlmPage from '../app/admin/llm/page';
import AdminUsersPage from '../app/admin/users/page';
import CrawlPage from '../app/crawl/page-view';
import DashboardPage from '../app/dashboard/page';
import DataEnrichmentPage from '../app/data-enrichment/page-view';
import JobsPage from '../app/jobs/page-view';
import LoginPage from '../app/login/page-view';
import ProductIntelligencePage from '../app/product-intelligence/product-intelligence-page';
import RegisterPage from '../app/register/page-view';
import RunTracePage from '../app/run-trace/run-trace-page';
import RunsPage from '../app/runs/page-view';
import SelectorsManagePage from '../components/selectors/domain-memory-manage-page';
import SelectorsPage from '../app/selectors/page-view';
import { AppShell } from '../components/layout/app-shell';
import { QueryProvider } from '../components/ui/query-provider';

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
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/:run_id" element={<RunDetailRedirect />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/selectors" element={<SelectorsPage />} />
            <Route path="/selectors/manage" element={<SelectorsManagePage />} />
            <Route path="/admin/users" element={<AdminUsersPage />} />
            <Route path="/admin/llm" element={<AdminLlmPage />} />
            <Route path="/data-enrichment" element={<DataEnrichmentPage />} />
            <Route path="/product-intelligence" element={<ProductIntelligencePage />} />
            <Route path="/run-trace" element={<RunTracePage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AppShell>
      </QueryProvider>
    </BrowserRouter>
  );
}
