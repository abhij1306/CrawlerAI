'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  Play,
  Search,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  SurfacePanel,
  TableSurface,
} from '../../components/ui/patterns';
import { Badge, Button } from '../../components/ui/primitives';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { api } from '../../lib/api';
import type { PlaygroundSessionResponse } from '../../lib/api/types';
import { cn } from '../../lib/utils';

// ─── Types ───────────────────────────────────────────────────────────────────

type SessionState =
  | 'created'
  | 'sitemap_listed'
  | 'discovering'
  | 'discovered'
  | 'extracting'
  | 'extracted'
  | 'running_pipeline'
  | 'complete';

type PlaygroundSession = PlaygroundSessionResponse;

type DiscoveredProduct = {
  url: string;
  title?: string;
  brand?: string;
  price?: string;
  image?: string;
};

type ExtractedRecord = {
  id: number;
  run_id: number;
  source_url: string;
  data: Record<string, unknown>;
};

// ─── Steps ───────────────────────────────────────────────────────────────────

const STEPS = [
  { id: 'discover', label: 'Discover' },
  { id: 'select', label: 'Select Products' },
  { id: 'extract', label: 'Extract' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'results', label: 'Results' },
] as const;

function stepIndex(state: SessionState): number {
  switch (state) {
    case 'created':
    case 'sitemap_listed':
    case 'discovering':
      return 0;
    case 'discovered':
      return 1;
    case 'extracting':
      return 2;
    case 'extracted':
      return 3;
    case 'running_pipeline':
    case 'complete':
      return 4;
    default:
      return 0;
  }
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function PlaygroundPage() {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
  const [pipelineOptions, setPipelineOptions] = useState({
    enrich: false,
    compare: false,
    monitor: false,
    audit: false,
  });

  // ─── Session polling ─────────────────────────────────────────────────────

  const sessionQuery = useQuery({
    queryKey: ['playground-session', sessionId],
    queryFn: () => api.getPlaygroundSession(sessionId!),
    enabled: sessionId !== null,
    refetchInterval: (query) => {
      const data = query.state.data;
      const state = data?.state;
      if (state === 'discovering' || state === 'extracting' || state === 'running_pipeline') {
        return 3000;
      }
      // Audit can run independently while the session stays in `extracted`.
      // Keep polling while the audit job is still in flight.
      const audit = data?.step_data?.audit as Record<string, unknown> | undefined;
      if (audit && audit.status === 'running') {
        return 3000;
      }
      return false;
    },
  });

  const session = sessionQuery.data as PlaygroundSession | undefined;
  const currentStep = session ? stepIndex(session.state as SessionState) : -1;
  const hasResultsState = session
    ? session.state === 'extracted' ||
      session.state === 'running_pipeline' ||
      session.state === 'complete'
    : false;

  const resultsQuery = useQuery({
    queryKey: ['playground-results', sessionId],
    queryFn: () => api.playgroundResults(sessionId!),
    enabled: sessionId !== null && hasResultsState,
    refetchInterval: () => {
      if (session?.state === 'running_pipeline') return 3000;
      const audit = session?.step_data?.audit as Record<string, unknown> | undefined;
      if (audit?.status === 'running') return 3000;
      return false;
    },
  });

  // ─── Mutations ───────────────────────────────────────────────────────────

  const createSession = useMutation({
    mutationFn: (inputUrl: string) =>
      api.createPlaygroundSession({ url: inputUrl }) as Promise<PlaygroundSession>,
    onSuccess: (data) => {
      setSessionId(data.id);
      setError('');
    },
    onError: (err: Error) => setError(err.message),
  });

  const startDiscover = useMutation({
    mutationFn: (sid: number) => api.playgroundDiscover(sid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['playground-session', sessionId] }),
    onError: (err: Error) => setError(err.message),
  });

  const selectProducts = useMutation({
    mutationFn: ({ sid, urls }: { sid: number; urls: string[] }) =>
      api.playgroundSelect(sid, { urls }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playground-session', sessionId] });
      // Auto-start extraction after successful selection
      if (sessionId) startExtract.mutate(sessionId);
    },
    onError: (err: Error) => setError(err.message),
  });

  const selectCategory = useMutation({
    mutationFn: ({ sid, categoryUrls }: { sid: number; categoryUrls: string[] }) =>
      api.playgroundSelectCategory(sid, { urls: categoryUrls }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['playground-session', sessionId] }),
    onError: (err: Error) => setError(err.message),
  });

  const startExtract = useMutation({
    mutationFn: (sid: number) => api.playgroundExtract(sid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['playground-session', sessionId] }),
    onError: (err: Error) => setError(err.message),
  });

  const runPipeline = useMutation({
    mutationFn: ({ sid, options }: { sid: number; options: typeof pipelineOptions }) =>
      api.playgroundPipeline(sid, options),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['playground-session', sessionId] }),
    onError: (err: Error) => setError(err.message),
  });

  // ─── Handlers ────────────────────────────────────────────────────────────

  const handleStart = useCallback(() => {
    const trimmed = url.trim();
    if (!trimmed) return;
    setError('');
    createSession.mutate(trimmed);
  }, [url, createSession]);

  const handleSelect = useCallback(() => {
    if (!sessionId || selectedUrls.size === 0) return;
    selectProducts.mutate({ sid: sessionId, urls: Array.from(selectedUrls) });
  }, [sessionId, selectedUrls, selectProducts]);

  const handlePipeline = useCallback(() => {
    if (!sessionId) return;
    runPipeline.mutate({ sid: sessionId, options: pipelineOptions });
  }, [sessionId, pipelineOptions, runPipeline]);

  const handleReset = useCallback(() => {
    setSessionId(null);
    setUrl('');
    setError('');
    setSelectedUrls(new Set());
    setPipelineOptions({ enrich: false, compare: false, monitor: false, audit: false });
  }, []);

  // Auto-start discovery after session creation
  // startDiscover omitted from deps: React Query mutation objects are referentially stable
  useEffect(() => {
    if (session?.state === 'created' && sessionId && !startDiscover.isPending) {
      startDiscover.mutate(sessionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.state, sessionId]);

  // Reset url selection when the session transitions into a stage with a
  // fresh picker (sitemap or discovered). Using the "derive state from prop"
  // pattern instead of a setState-in-effect avoids cascading renders flagged
  // by react-hooks/set-state-in-effect.
  const [prevSelectionStage, setPrevSelectionStage] = useState(session?.state);
  if (session?.state !== prevSelectionStage) {
    setPrevSelectionStage(session?.state);
    if (session?.state === 'sitemap_listed' || session?.state === 'discovered') {
      setSelectedUrls(new Set());
    }
  }

  // ─── Derived data ────────────────────────────────────────────────────────

  const discoveredProducts: DiscoveredProduct[] = (() => {
    const discover = session?.step_data?.discover;
    if (discover && typeof discover === 'object' && 'products' in discover) {
      const products = (discover as Record<string, unknown>).products;
      return Array.isArray(products) ? (products as DiscoveredProduct[]) : [];
    }
    return [];
  })();

  const sitemapUrls: string[] = (() => {
    const sitemap = session?.step_data?.sitemap;
    if (sitemap && typeof sitemap === 'object' && 'urls' in sitemap) {
      const urls = (sitemap as Record<string, unknown>).urls;
      return Array.isArray(urls) ? (urls as string[]) : [];
    }
    return [];
  })();

  const sitemapSource = (() => {
    const sitemap = session?.step_data?.sitemap;
    if (sitemap && typeof sitemap === 'object' && 'source' in sitemap) {
      const source = (sitemap as Record<string, unknown>).source;
      return source === 'homepage' ? 'homepage' : 'sitemap';
    }
    return 'sitemap';
  })();

  const resultsSteps = (() => {
    const payload = resultsQuery.data;
    if (payload && typeof payload === 'object' && 'steps' in payload) {
      const steps = (payload as Record<string, unknown>).steps;
      return steps && typeof steps === 'object' ? (steps as Record<string, unknown>) : undefined;
    }
    return undefined;
  })();

  const extractedRecords: ExtractedRecord[] = (() => {
    const extract = resultsSteps?.extract;
    if (extract && typeof extract === 'object' && 'records' in extract) {
      const records = (extract as Record<string, unknown>).records;
      return Array.isArray(records) ? (records as ExtractedRecord[]) : [];
    }
    return [];
  })();

  const extractedRunIds: number[] = (() => {
    const extract = resultsSteps?.extract;
    if (extract && typeof extract === 'object' && 'run_ids' in extract) {
      const runIds = (extract as Record<string, unknown>).run_ids;
      return Array.isArray(runIds)
        ? runIds.filter((value): value is number => typeof value === 'number')
        : [];
    }
    return [];
  })();

  const hasPipelineActivity = Boolean(
    session?.step_data?.enrich ||
    session?.step_data?.compare ||
    session?.step_data?.monitor ||
    session?.step_data?.audit,
  );

  const toggleProduct = (productUrl: string) => {
    setSelectedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(productUrl)) {
        next.delete(productUrl);
      } else if (next.size < 50) {
        next.add(productUrl);
      }
      return next;
    });
  };

  const selectAll = () => {
    const all = discoveredProducts.slice(0, 50).map((p) => p.url);
    setSelectedUrls(new Set(all));
  };

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Playground"
        description="Explore any domain — discover, extract, enrich, compare, and monitor from one place."
        actions={
          session ? (
            <Button size="sm" variant="ghost" onClick={handleReset}>
              Start New
            </Button>
          ) : undefined
        }
      />

      {error && <InlineAlert message={error} />}

      {/* ─── URL Input (no session yet) ─────────────────────────────────── */}
      {!session && (
        <SurfacePanel>
          <div className="p-6">
            <h3 className="type-heading-3 mb-2">Enter a URL to explore</h3>
            <p className="type-body-sm mb-4">
              Paste a category page, brand page, or product listing URL. The system will discover
              what products are available.
            </p>
            <div className="flex gap-3">
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleStart()}
                placeholder="https://www.example.com/category/shoes"
                className="border-divider focus-ring bg-panel flex-1 rounded-md border px-3 py-2 text-sm"
              />
              <Button onClick={handleStart} disabled={createSession.isPending || !url.trim()}>
                {createSession.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Search className="size-4" />
                )}
                Explore
              </Button>
            </div>
          </div>
        </SurfacePanel>
      )}

      {/* ─── Stepper ────────────────────────────────────────────────────── */}
      {session && (
        <>
          <div className="flex items-center gap-2 text-sm">
            {STEPS.map((step, idx) => (
              <div key={step.id} className="flex items-center gap-1.5">
                {idx < currentStep ? (
                  <CheckCircle2 className="text-success size-4" />
                ) : idx === currentStep ? (
                  <Circle className="text-accent size-4 fill-[var(--accent)]" />
                ) : (
                  <Circle className="text-muted size-4" />
                )}
                <span
                  className={cn(
                    'font-medium',
                    idx === currentStep && 'text-accent',
                    idx > currentStep && 'text-muted',
                  )}
                >
                  {step.label}
                </span>
                {idx < STEPS.length - 1 && <ArrowRight className="text-muted mx-1 size-3" />}
              </div>
            ))}
          </div>

          {/* ─── Step: Discovering ──────────────────────────────────────── */}
          {(session.state === 'discovering' || session.state === 'created') && (
            <ActivityLogPanel
              title="Discovering products"
              subtitle={
                <>
                  Crawling <span className="font-mono">{session.input_url}</span> to find available
                  products.
                </>
              }
              runId={
                (session.step_data?.discover as Record<string, unknown>)?.run_id as
                  | number
                  | undefined
              }
              startedAt={session.created_at}
              phase="discover"
            />
          )}

          {/* ─── Step: Sitemap → pick a category ────────────────────────── */}
          {session.state === 'sitemap_listed' && (
            <PickerPanel
              mode="multi"
              title={`URLs from ${sitemapSource === 'homepage' ? 'homepage' : 'sitemap'} (${sitemapUrls.length})`}
              description={
                sitemapSource === 'homepage'
                  ? 'Sitemap was unavailable, so these links were inferred from the homepage. Pick one or more URLs to crawl.'
                  : 'Pick one or more category, collection, or section URLs to crawl.'
              }
              items={sitemapUrls.map((u) => ({ url: u }))}
              selected={selectedUrls}
              onToggle={toggleProduct}
              onSelectAll={() => setSelectedUrls(new Set(sitemapUrls.slice(0, 50)))}
              onConfirm={() => {
                const categoryUrls = Array.from(selectedUrls);
                if (sessionId && categoryUrls.length > 0) {
                  selectCategory.mutate({ sid: sessionId, categoryUrls });
                }
              }}
              confirmLabel={
                selectedUrls.size === 0
                  ? 'Pick URL(s)'
                  : `Crawl ${selectedUrls.size} URL${selectedUrls.size === 1 ? '' : 's'}`
              }
              confirmDisabled={selectedUrls.size === 0 || selectCategory.isPending}
              isLoading={selectCategory.isPending}
              emptyTitle="No homepage or sitemap links found"
              emptyDescription={`Couldn't pull useful links from sitemap or homepage for ${session.input_url}. Try a category or product URL directly.`}
            />
          )}

          {/* ─── Step: Select Products ─────────────────────────────────── */}
          {session.state === 'discovered' && (
            <PickerPanel
              mode="multi"
              title={`Products Found (${discoveredProducts.length})`}
              description="Select up to 50 products to extract detailed data from."
              items={discoveredProducts}
              selected={selectedUrls}
              onToggle={toggleProduct}
              onSelectAll={selectAll}
              onConfirm={handleSelect}
              confirmLabel={`Extract ${selectedUrls.size} Product${selectedUrls.size === 1 ? '' : 's'}`}
              confirmDisabled={selectedUrls.size === 0 || selectProducts.isPending}
              isLoading={selectProducts.isPending}
              emptyTitle="No products found"
              emptyDescription="The crawl didn't find product links on this page. Try a different URL."
            />
          )}

          {/* ─── Step: Extracting ──────────────────────────────────────── */}
          {session.state === 'extracting' && (
            <ActivityLogPanel
              title="Extracting product details"
              subtitle={
                <>
                  Crawling{' '}
                  {String(
                    (session.step_data?.extract as Record<string, unknown>)?.url_count ?? '?',
                  )}{' '}
                  product pages for structured data.
                </>
              }
              runId={
                (session.step_data?.extract as Record<string, unknown>)?.run_id as
                  | number
                  | undefined
              }
              startedAt={session.updated_at}
              phase="extract"
            />
          )}

          {/* ─── Step: Pipeline Selection ──────────────────────────────── */}
          {session.state === 'extracted' && (
            <>
              <ExtractedDataPreview records={extractedRecords} isLoading={resultsQuery.isPending} />
              <SurfacePanel>
                <div className="border-divider border-b px-4 py-3">
                  <p className="type-label m-0">Extraction Complete</p>
                  <p className="text-muted m-0 text-sm">
                    Choose what to do with the extracted data.
                  </p>
                </div>
                <div className="grid gap-4 p-6 sm:grid-cols-2">
                  <label className="border-divider hover:bg-background-alt flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition">
                    <input
                      type="checkbox"
                      checked={pipelineOptions.enrich}
                      onChange={(e) =>
                        setPipelineOptions((prev) => ({ ...prev, enrich: e.target.checked }))
                      }
                      className="mt-0.5 size-4 rounded"
                    />
                    <div>
                      <p className="m-0 text-sm font-medium">Enrich Data</p>
                      <p className="text-muted m-0 text-xs">
                        Fill missing brand, category, and product attributes.
                      </p>
                    </div>
                  </label>
                  <label className="border-divider hover:bg-background-alt flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition">
                    <input
                      type="checkbox"
                      checked={pipelineOptions.compare}
                      onChange={(e) =>
                        setPipelineOptions((prev) => ({ ...prev, compare: e.target.checked }))
                      }
                      className="mt-0.5 size-4 rounded"
                    />
                    <div>
                      <p className="m-0 text-sm font-medium">Product Intelligence</p>
                      <p className="text-muted m-0 text-xs">
                        Find competitor prices on Google, Amazon, Flipkart.
                      </p>
                    </div>
                  </label>
                  <label className="border-divider hover:bg-background-alt flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition">
                    <input
                      type="checkbox"
                      checked={pipelineOptions.monitor}
                      onChange={(e) =>
                        setPipelineOptions((prev) => ({ ...prev, monitor: e.target.checked }))
                      }
                      className="mt-0.5 size-4 rounded"
                    />
                    <div>
                      <p className="m-0 text-sm font-medium">Create Monitor</p>
                      <p className="text-muted m-0 text-xs">
                        Watch for price and availability changes on these products.
                      </p>
                    </div>
                  </label>
                  <label className="border-divider hover:bg-background-alt flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition">
                    <input
                      type="checkbox"
                      checked={pipelineOptions.audit}
                      onChange={(e) =>
                        setPipelineOptions((prev) => ({ ...prev, audit: e.target.checked }))
                      }
                      className="mt-0.5 size-4 rounded"
                    />
                    <div>
                      <p className="m-0 text-sm font-medium">AI Audit</p>
                      <p className="text-muted m-0 text-xs">
                        Check AI discoverability score for the source domain.
                      </p>
                      <Badge tone="info" className="mt-1">
                        Independent — runs on input URL
                      </Badge>
                    </div>
                  </label>
                </div>
                <div className="border-divider flex justify-end border-t px-4 py-3">
                  <Button
                    onClick={handlePipeline}
                    disabled={
                      runPipeline.isPending ||
                      (!pipelineOptions.enrich &&
                        !pipelineOptions.compare &&
                        !pipelineOptions.monitor &&
                        !pipelineOptions.audit)
                    }
                  >
                    {runPipeline.isPending ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Play className="size-4" />
                    )}
                    Run Pipeline
                  </Button>
                </div>
              </SurfacePanel>
              {hasPipelineActivity && (
                <PipelineResultsPanel session={session} extractedRunIds={extractedRunIds} />
              )}
            </>
          )}

          {/* ─── Step: Pipeline Running / Results ──────────────────────── */}
          {(session.state === 'running_pipeline' || session.state === 'complete') && (
            <>
              <ExtractedDataPreview records={extractedRecords} isLoading={resultsQuery.isPending} />
              <PipelineResultsPanel
                session={session}
                extractedRunIds={extractedRunIds}
                onReset={handleReset}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}

// ─── Sub-Components ────────────────────────────────────────────────────────────

// Phase = which step's logs we're showing. Used to seed milestone copy.
type ActivityPhase = 'discover' | 'extract';

type ActivityEntry = {
  key: string;
  text: string;
  status: 'done' | 'active' | 'pending';
  timestamp?: string;
};

// Map raw backend log messages to short, human-friendly lines.
// Returns null to drop noisy entries.
function humanizeLogMessage(raw: string): string | null {
  let msg = raw.trim();
  if (!msg) return null;

  // Strip [url:...] prefix if present
  const urlPrefixRegex = /^\[url:(https?:\/\/[^\s\]]+)\]\s*/i;
  msg = msg.replace(urlPrefixRegex, '').trim();
  if (!msg) return null;

  // Skip framework/internal noise
  if (/^\[corr:/i.test(msg)) return null;
  if (/^\[ROBOTS\]/i.test(msg) && /No robots\.txt/i.test(msg)) return null;
  if (/listing_escalation_skipped/i.test(msg)) return null;

  // Friendly rewrites for common signals
  if (/Resolved \d+ seed URL/i.test(msg)) {
    const m = msg.match(/Resolved (\d+) seed URL/i);
    return m ? `Resolved ${m[1]} target URL${m[1] === '1' ? '' : 's'}` : 'Resolved target URLs';
  }
  if (/Starting crawl run/i.test(msg)) return 'Connecting to target site';
  if (/Launched .* browser/i.test(msg)) return 'Launching browser engine';
  if (/Rotating proxy profile detected/i.test(msg)) return 'Rotating proxy profile';
  if (/Page loaded in \d+ms/i.test(msg)) {
    const m = msg.match(/Page loaded in (\d+)ms/i);
    return m ? `Page loaded (${m[1]}ms)` : 'Page loaded';
  }
  if (/Acquired payload via/i.test(msg)) return 'Fetched page content';
  if (/HTTP transport fallback/i.test(msg)) return 'Retrying with alternate transport';
  if (/Escalating to browser/i.test(msg)) return 'Escalating to full browser render';
  if (/Traversal complete/i.test(msg)) return 'Finished page traversal';
  if (/scroll|load_more|paginate/i.test(msg) && /traversal|listing/i.test(msg)) {
    return 'Discovered pagination pattern';
  }
  if (/Normalized \d+ record/i.test(msg)) {
    const m = msg.match(/Normalized (\d+) record/i);
    return m ? `Parsed ${m[1]} record${m[1] === '1' ? '' : 's'}` : 'Parsing records';
  }
  if (/Persisted \d+ record/i.test(msg)) {
    const m = msg.match(/Persisted (\d+) record/i);
    return m ? `Saved ${m[1]} record${m[1] === '1' ? '' : 's'}` : 'Saving records';
  }
  if (/Extracted \d+ records/i.test(msg)) {
    const m = msg.match(/Extracted (\d+) records using ([\w-]+)/i);
    return m ? `Extracted ${m[1]} record${m[1] === '1' ? '' : 's'} (${m[2]})` : 'Extracted records';
  }
  if (/Pipeline finished/i.test(msg)) {
    const m = msg.match(/Pipeline finished\. (\d+) records/i);
    return m ? `Run complete (${m[1]} record${m[1] === '1' ? '' : 's'})` : 'Run complete';
  }
  if (/Stopped after reaching max_records/i.test(msg)) return 'Reached record limit';
  if (/retrying browser render/i.test(msg)) return 'Retrying with browser render';

  // Fall back to the raw message, trimmed for length.
  if (msg.length > 120) return `${msg.slice(0, 117)}…`;
  return msg;
}

function ActivityLogPanel({
  title,
  subtitle,
  runId,
  startedAt,
  phase,
}: {
  title: string;
  subtitle: React.ReactNode;
  runId?: number;
  startedAt?: string;
  phase: ActivityPhase;
}) {
  // Poll backend logs for this run while the panel is mounted.
  const logsQuery = useQuery({
    queryKey: ['playground-crawl-logs', runId],
    queryFn: () => api.getCrawlLogs(runId!, { limit: 200 }),
    enabled: runId !== undefined && runId !== null,
    refetchInterval: 2000,
  });

  // Live elapsed clock so the UI never looks frozen even with no log activity.
  // Date.now / Date.parse are impure, so we initialize via lazy useState and
  // resync when startedAt changes (derive-from-prop pattern). useMemo would
  // be flagged by react-hooks/purity for calling impure functions.
  const computeStartMs = (value: string | undefined): number =>
    value ? Date.parse(value) : Date.now();
  const [startMs, setStartMs] = useState(() => computeStartMs(startedAt));
  const [prevStartedAt, setPrevStartedAt] = useState(startedAt);
  if (startedAt !== prevStartedAt) {
    setPrevStartedAt(startedAt);
    setStartMs(computeStartMs(startedAt));
  }
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const elapsedSec = Math.max(0, Math.floor((now - startMs) / 1000));
  const slow = elapsedSec >= 30;
  const stalled = elapsedSec >= 90;

  // Build the rendered entries: a small set of seeded milestones followed by
  // humanized real backend logs. Earlier entries are marked done; the last
  // one becomes the active spinner row.
  const entries: ActivityEntry[] = useMemo(() => {
    const seeded: ActivityEntry[] =
      phase === 'discover'
        ? [
            { key: 'seed-init', text: 'Session started', status: 'done' },
            { key: 'seed-resolve', text: 'Resolving target URL', status: 'done' },
          ]
        : [
            { key: 'seed-init', text: 'Extraction job created', status: 'done' },
            { key: 'seed-batch', text: 'Queued selected pages', status: 'done' },
          ];

    const rawLogs = logsQuery.data ?? [];
    const seen = new Set<string>();
    const fromLogs: ActivityEntry[] = [];
    for (const log of rawLogs) {
      const text = humanizeLogMessage(log.message);
      if (!text) continue;
      // Dedupe consecutive identical lines (e.g. repeated page-loaded events).
      if (seen.has(text)) continue;
      seen.add(text);
      fromLogs.push({
        key: `log-${log.id}`,
        text,
        status: 'done',
        timestamp: log.created_at,
      });
    }

    const all = [...seeded, ...fromLogs];

    // The last visible entry is the one currently in flight; everything
    // before it is done. We always show an active row to keep the spinner
    // alive — derive it from the most recent log if we have one, otherwise
    // fall back to a generic phase message.
    const activeText = phase === 'discover' ? 'Parsing response' : 'Parsing extracted data';
    if (all.length === 0) {
      all.push({ key: 'active-fallback', text: activeText, status: 'active' });
    } else {
      // Promote the last entry to active.
      const last = all[all.length - 1];
      all[all.length - 1] = { ...last, status: 'active' };
    }
    return all;
  }, [logsQuery.data, phase]);

  const elapsedLabel =
    elapsedSec < 60 ? `${elapsedSec}s` : `${Math.floor(elapsedSec / 60)}m ${elapsedSec % 60}s`;

  return (
    <SurfacePanel>
      <div className="border-divider flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-3">
          <Loader2 className="text-accent size-5 animate-spin" />
          <div>
            <p className="m-0 font-medium">{title}</p>
            <p className="text-muted m-0 text-sm">{subtitle}</p>
          </div>
        </div>
        <span className="text-muted font-mono text-xs">{elapsedLabel}</span>
      </div>
      <ul className="space-y-2 px-6 py-4 text-sm">
        {entries.map((entry) => (
          <li key={entry.key} className="flex items-start gap-2">
            {entry.status === 'done' && (
              <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" />
            )}
            {entry.status === 'active' && (
              <Loader2 className="text-accent mt-0.5 size-4 shrink-0 animate-spin" />
            )}
            {entry.status === 'pending' && <Circle className="text-muted mt-0.5 size-4 shrink-0" />}
            <span className={cn(entry.status === 'pending' && 'text-muted')}>{entry.text}</span>
          </li>
        ))}
      </ul>
      {slow && (
        <div className="border-divider flex items-start gap-2 border-t px-6 py-3 text-xs">
          <AlertTriangle
            className={cn('mt-0.5 size-4 shrink-0', stalled ? 'text-danger' : 'text-warning')}
          />
          <span className="text-muted">
            {stalled
              ? 'This is taking longer than usual. The site may have heavy bot defenses or the page may be slow to render. You can keep waiting or start a new session with a different URL.'
              : 'Still working. Some sites with strong bot protection take longer to crawl.'}
          </span>
        </div>
      )}
    </SurfacePanel>
  );
}

function PickerPanel({
  mode,
  title,
  description,
  items,
  selected,
  onToggle,
  onSelectAll,
  onConfirm,
  confirmLabel,
  confirmDisabled,
  isLoading,
  emptyTitle,
  emptyDescription,
}: {
  mode: 'single' | 'multi';
  title: string;
  description: string;
  items: DiscoveredProduct[];
  selected: Set<string>;
  onToggle: (url: string) => void;
  onSelectAll?: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  confirmDisabled: boolean;
  isLoading: boolean;
  emptyTitle: string;
  emptyDescription: string;
}) {
  const showBrandPrice = items.some((item) => item.brand || item.price || item.title);
  return (
    <SurfacePanel>
      <div className="border-divider flex items-center justify-between border-b px-4 py-3">
        <div>
          <p className="type-label m-0">{title}</p>
          <p className="text-muted m-0 text-sm">{description}</p>
        </div>
        <div className="flex gap-2">
          {mode === 'multi' && onSelectAll && items.length > 0 && (
            <Button size="sm" variant="ghost" onClick={onSelectAll}>
              Select All (max 50)
            </Button>
          )}
          <Button size="sm" onClick={onConfirm} disabled={confirmDisabled}>
            {isLoading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Play className="size-3.5" />
            )}
            {confirmLabel}
          </Button>
        </div>
      </div>
      <TableSurface>
        {items.length === 0 ? (
          <DataRegionEmpty title={emptyTitle} description={emptyDescription} />
        ) : (
          <Table className="compact-data-table">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[40px]">{''}</TableHead>
                <TableHead>{showBrandPrice ? 'Product' : 'URL'}</TableHead>
                {showBrandPrice && (
                  <>
                    <TableHead className="w-[120px]">Brand</TableHead>
                    <TableHead className="w-[100px]">Price</TableHead>
                  </>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.slice(0, 50).map((item) => {
                const isChecked = selected.has(item.url);
                return (
                  <TableRow
                    key={item.url}
                    className="cursor-pointer"
                    onClick={(e) => {
                      if ((e.target as HTMLElement).tagName === 'INPUT') return;
                      onToggle(item.url);
                    }}
                  >
                    <TableCell>
                      <input
                        type={mode === 'single' ? 'radio' : 'checkbox'}
                        name={mode === 'single' ? 'picker-single' : undefined}
                        checked={isChecked}
                        onChange={() => onToggle(item.url)}
                        onClick={(e) => e.stopPropagation()}
                        className="size-4 rounded"
                      />
                    </TableCell>
                    <TableCell>
                      <div className="min-w-0">
                        <p className="m-0 truncate text-sm font-medium">{item.title || item.url}</p>
                        {item.title && (
                          <p className="text-muted m-0 truncate font-mono text-xs">{item.url}</p>
                        )}
                      </div>
                    </TableCell>
                    {showBrandPrice && (
                      <>
                        <TableCell className="truncate text-sm">{item.brand || '-'}</TableCell>
                        <TableCell className="text-sm">{item.price || '-'}</TableCell>
                      </>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </TableSurface>
    </SurfacePanel>
  );
}

function PipelineStepCard({
  label,
  stepData,
}: {
  label: string;
  stepData?: Record<string, unknown>;
}) {
  if (!stepData) return null;

  const status = stepData.status as string;
  return (
    <div className="border-divider flex items-center justify-between rounded-md border px-4 py-3">
      <div className="flex items-center gap-2">
        {status === 'running' && <Loader2 className="text-accent size-4 animate-spin" />}
        {status === 'completed' && <CheckCircle2 className="text-success size-4" />}
        {status === 'created' && <Circle className="text-muted size-4" />}
        {status === 'failed' && <Circle className="text-danger size-4" />}
        <span className="text-sm font-medium">{label}</span>
      </div>
      {status !== 'failed' && (
        <Badge tone={status === 'running' ? 'info' : 'neutral'}>
          {status ? status.charAt(0).toUpperCase() + status.slice(1) : status}
        </Badge>
      )}
    </div>
  );
}

function ExtractedDataPreview({
  records,
  isLoading,
}: {
  records: ExtractedRecord[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <SurfacePanel>
        <div className="p-4">
          <DataRegionLoading count={3} />
        </div>
      </SurfacePanel>
    );
  }

  if (records.length === 0) {
    return (
      <SurfacePanel>
        <div className="p-4">
          <DataRegionEmpty
            title="No records extracted"
            description="The crawl completed but produced no structured records."
          />
        </div>
      </SurfacePanel>
    );
  }

  // Get field names from first record
  const fieldNames = Object.keys(records[0]?.data ?? {}).slice(0, 6);

  return (
    <SurfacePanel>
      <div className="border-divider flex items-center justify-between border-b px-4 py-3">
        <div>
          <p className="type-label m-0">Extracted Data ({records.length} records)</p>
          <p className="text-muted m-0 text-sm">Preview across all extracted product pages.</p>
        </div>
      </div>
      <TableSurface>
        <Table className="compact-data-table">
          <TableHeader>
            <TableRow>
              {fieldNames.map((field) => (
                <TableHead key={field}>{field}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {records.slice(0, 10).map((record) => (
              <TableRow key={record.id}>
                {fieldNames.map((field) => (
                  <TableCell key={field} className="max-w-[200px] truncate text-sm">
                    {String((record.data as Record<string, unknown>)?.[field] ?? '-')}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableSurface>
    </SurfacePanel>
  );
}

function PipelineResultsPanel({
  session,
  extractedRunIds,
  onReset,
}: {
  session: PlaygroundSession;
  extractedRunIds: number[];
  onReset?: () => void;
}) {
  const isRunning = session.state === 'running_pipeline';

  return (
    <SurfacePanel>
      <div className="border-divider border-b px-4 py-3">
        <p className="type-label m-0">Pipeline Results</p>
        <p className="text-muted m-0 text-sm">
          {isRunning ? 'Operations in progress...' : 'Latest downstream job state.'}
        </p>
      </div>
      <div className="space-y-3 p-4">
        <PipelineStepCard
          label="Enrichment"
          stepData={session.step_data?.enrich as Record<string, unknown> | undefined}
        />
        <PipelineStepCard
          label="Product Intelligence"
          stepData={session.step_data?.compare as Record<string, unknown> | undefined}
        />
        <PipelineStepCard
          label="Monitor"
          stepData={session.step_data?.monitor as Record<string, unknown> | undefined}
        />
        <PipelineStepCard
          label="AI Audit"
          stepData={session.step_data?.audit as Record<string, unknown> | undefined}
        />
      </div>
      {(onReset || extractedRunIds.length > 0) && (
        <div className="border-divider flex gap-2 border-t px-4 py-3">
          {onReset && (
            <Button size="sm" variant="ghost" onClick={onReset}>
              Start New Session
            </Button>
          )}
          {extractedRunIds[0] ? (
            <Button size="sm" variant="action" asChild>
              <a
                href={`/runs?run_id=${String(extractedRunIds[0])}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink className="size-3.5" />
                View Run
              </a>
            </Button>
          ) : null}
        </div>
      )}
    </SurfacePanel>
  );
}
