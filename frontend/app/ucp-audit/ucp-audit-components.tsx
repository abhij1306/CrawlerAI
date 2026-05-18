'use client';

import { useMemo, useState } from 'react';
import {
  Check,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Search,
  X,
  AlertTriangle,
  Layers,
  CheckSquare,
  Info,
  ChevronRight,
  Sparkles,
  ShieldAlert,
  ArrowRight,
} from 'lucide-react';

import {
  DataRegionEmpty,
  DataRegionLoading,
  TableSurface,
} from '../../components/ui/patterns';
import { Badge, Button, Input } from '../../components/ui/primitives';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { api } from '../../lib/api';
import { cn } from '../../lib/utils';
import type { UcpAuditJob, UcpAuditReport } from '../../lib/api/types';
import { syntaxHighlightJson } from '../../lib/ui/syntax';

const DIMENSION_META: Record<string, { label: string; subtitle: string; desc: string }> = {
  'D-UCP1': {
    label: 'Discovery',
    subtitle: 'Manifest validity',
    desc: 'Verifies the presence and structure of the /.well-known/ucp manifest defining shopping services.',
  },
  'D-UCP2': {
    label: 'Product Schema',
    subtitle: 'JSON-LD structure',
    desc: 'Analyzes core Product schema completeness and checks for valid machine-readable attributes.',
  },
  'D-UCP3': {
    label: 'Metafield Coverage',
    subtitle: 'Critical commerce properties',
    desc: 'Measures exposure of essential attributes: size, color, brand, GTIN, and material.',
  },
  'D-UCP4': {
    label: 'Taxonomy Alignment',
    subtitle: 'Category consistency',
    desc: 'Checks Google Product Taxonomy categorization for standard catalog faceting and search placement.',
  },
  'D-UCP5': {
    label: 'Variant Fidelity',
    subtitle: 'Per-SKU price/availability',
    desc: 'Ensures each variant has structured Offers rather than collapsed values, maintaining checkout trust.',
  },
  'D-UCP6': {
    label: 'Policy Readability',
    subtitle: 'Return & shipping terms',
    desc: 'Validates delivery times, pricing, return windows, and active three-letter currency formats.',
  },
  'D-UCP7': {
    label: 'Agent-View Delta',
    subtitle: 'Fidelity differences',
    desc: 'Measures mismatch gaps between raw HTTP-extracted payload and rendered browser elements.',
  },
};

const FINDING_COPY: Record<
  string,
  { description: string; fix: string; effort: string; action: string; impact: 'critical' | 'high' | 'medium' }
> = {
  manifest_missing: {
    description: 'UCP manifest was not found at /.well-known/ucp, so agents cannot discover the store contract.',
    fix: 'Enable Shopify UCP or publish a valid /.well-known/ucp manifest with shopping services.',
    effort: '15 min',
    action: 'Publish a valid UCP manifest',
    impact: 'critical',
  },
  manifest_invalid: {
    description: 'UCP manifest exists but does not declare the required shopping service contract.',
    fix: 'Expose dev.ucp.shopping services or the required product discovery, checkout, and orders capabilities.',
    effort: '1 hour',
    action: 'Fix manifest service declarations',
    impact: 'critical',
  },
  product_sample_missing: {
    description: 'No product detail pages were sampled, so product-level agent readability could not be measured.',
    fix: 'Make product URLs discoverable through sitemap.xml or collection links.',
    effort: '2 hours',
    action: 'Expose discoverable product URLs',
    impact: 'high',
  },
  product_jsonld_missing: {
    description: 'Sampled product pages are missing Product JSON-LD.',
    fix: 'Add Product or ProductGroup JSON-LD to product templates.',
    effort: '1 sprint',
    action: 'Add Product JSON-LD',
    impact: 'critical',
  },
  product_schema_required_missing: {
    description: 'Required fields such as price, availability, or currency are missing from product JSON-LD.',
    fix: 'Populate name, offers.price, offers.availability, and offers.priceCurrency on every PDP.',
    effort: '2 hours',
    action: 'Fill required JSON-LD offer fields',
    impact: 'critical',
  },
  product_schema_recommended_missing: {
    description: 'Recommended identity fields such as SKU, brand, image, description, or GTIN are incomplete.',
    fix: 'Expose brand, SKU, GTIN/barcode, image, and description in product JSON-LD.',
    effort: '1 sprint',
    action: 'Add recommended identity fields',
    impact: 'high',
  },
  product_additional_property_missing: {
    description: 'additionalProperty is empty, so agents cannot filter by size, color, material, brand, or GTIN.',
    fix: 'Map Shopify variant options and product metafields into JSON-LD additionalProperty.',
    effort: '1 sprint',
    action: 'Map attributes to additionalProperty',
    impact: 'critical',
  },
  metafield_critical_gap: {
    description: 'Critical commerce attributes are not exposed as JSON-LD additionalProperty.',
    fix: 'Expose size, color, material, brand, and GTIN as structured additionalProperty values.',
    effort: '1 sprint',
    action: 'Expose critical metafields',
    impact: 'critical',
  },
  taxonomy_inconsistent: {
    description: 'Product category values are shallow or inconsistent, reducing agent faceting quality.',
    fix: 'Standardize product_type and set a deep Google Product Category path for all sampled products.',
    effort: '2-4 hours',
    action: 'Standardize product taxonomy',
    impact: 'medium',
  },
  variant_offers_collapsed: {
    description: 'Multiple variants appear to share one offer, hiding per-SKU price differences from agents.',
    fix: 'Emit one structured Offer per variant with independent price, currency, SKU, and availability.',
    effort: 'custom dev',
    action: 'Expand variant offers',
    impact: 'critical',
  },
  variant_sku_missing: {
    description: 'Variant SKUs are missing, making product identity weak for agent checkout.',
    fix: 'Populate SKU or barcode for each variant and expose it in structured data.',
    effort: '2 hours',
    action: 'Add variant SKUs',
    impact: 'high',
  },
  variant_availability_missing: {
    description: 'Variant availability is missing from structured data.',
    fix: 'Expose InStock, OutOfStock, or PreOrder availability per variant offer.',
    effort: '2 hours',
    action: 'Add variant availability',
    impact: 'high',
  },
  price_integrity_discount_mismatch: {
    description: 'Human-visible discount messaging is not reflected in structured offers.price.',
    fix: 'Align JSON-LD price with the effective transaction price or expose discount metadata.',
    effort: '1 sprint',
    action: 'Align agent price with checkout price',
    impact: 'critical',
  },
  policy_shipping_missing: {
    description: 'No shippingDetails are present in JSON-LD, so agents cannot answer delivery questions reliably.',
    fix: 'Add shippingDetails with shippingRate and deliveryTime to product offers.',
    effort: '2 hours',
    action: 'Add structured shipping policy',
    impact: 'medium',
  },
  policy_return_period_missing: {
    description: 'Return window is not machine-readable.',
    fix: 'Add merchantReturnPolicy with merchantReturnDays to product JSON-LD.',
    effort: '2 hours',
    action: 'Add structured return policy',
    impact: 'medium',
  },
  policy_currency_invalid: {
    description: 'Currency is missing or not ISO-4217 structured.',
    fix: 'Expose a valid three-letter priceCurrency value such as USD or INR.',
    effort: '15 min',
    action: 'Fix structured currency',
    impact: 'high',
  },
  policy_page_inaccessible: {
    description: 'Policy page could not be reached over HTTP.',
    fix: 'Expose a crawlable returns or shipping policy URL.',
    effort: '1 hour',
    action: 'Make policy page crawlable',
    impact: 'medium',
  },
  agent_delta_low_fidelity: {
    description: 'The agent-readable view misses important browser-visible commerce signals.',
    fix: 'Move price, variant options, discounts, and policy facts from rendered-only UI into structured data.',
    effort: '1 sprint',
    action: 'Close agent vs human view gaps',
    impact: 'critical',
  },
  agent_delta_disabled: {
    description: 'Agent delta was not run for this audit, so the report cannot show a live HTTP-vs-browser diff.',
    fix: 'Turn on Agent Delta before starting the next audit.',
    effort: 'rerun',
    action: 'Run audit with Agent Delta enabled',
    impact: 'medium',
  },
  agent_delta_unavailable: {
    description: 'Agent delta could not complete for the sampled product.',
    fix: 'Retry with browser acquisition available and inspect acquisition diagnostics if it fails again.',
    effort: 'debug',
    action: 'Retry agent delta',
    impact: 'high',
  },
};

type NormalizedFinding = {
  id: string;
  code: string;
  dimension: string;
  severity: string;
  description: string;
  fix: string;
  effort: string;
  action: string;
  impact: 'critical' | 'high' | 'medium';
  affected: number;
  countKind: string;
  affectedUrls: string[];
  evidence: Array<Record<string, unknown>>;
};

type AgentViewSample = {
  url: string;
  agent_extracted: Record<string, unknown>;
  human_visible: Record<string, unknown>;
  missing_in_agent_view: string[];
  agent_only_signals: string[];
  fidelity_score: number;
};

export function UcpScoreSummary({
  report,
  job,
}: Readonly<{ report: UcpAuditReport | null; job: UcpAuditJob | null }>) {
  const score = report?.overall_score ?? Number(job?.summary?.overall_score ?? 0);
  const findings = useNormalizedFindings(report);
  const blocking = findings.filter((finding) => finding.severity === 'blocking').length;
  const warnings = findings.filter((finding) => finding.severity !== 'blocking').length;
  const gateApplied = Boolean(report?.report_json?.d_ucp1_gate_applied);

  return (
    <section className="border-border bg-panel overflow-hidden rounded-[var(--radius-lg)] border shadow-sm">
      <div className="grid gap-0 lg:grid-cols-[300px_1fr]">

        {/* Overall Score Bento Card */}
        <div className="border-divider bg-background/30 flex flex-col items-center justify-center border-b p-6 lg:border-b-0 lg:border-r relative">
          <div className="absolute top-3 inset-x-0 flex items-center justify-center gap-1.5">
            <Sparkles className="size-3 text-accent animate-pulse" />
            <span className="text-[10px] font-normal font-sans tracking-widest text-muted uppercase">COMPLIANCE INDEX</span>
          </div>

          <div className="my-2 relative flex items-center justify-center">
            {/* Glowing Ring Background effect */}
            <div className={cn(
              "absolute inset-0 rounded-full blur-xl opacity-10 transition-colors duration-1000",
              score >= 80 ? "bg-success" : score >= 50 ? "bg-warning" : "bg-danger"
            )} />
            <ScoreRing score={report ? score : 0} size={156} stroke={10} label="Overall Index" />
          </div>

          <div className="mt-4 flex flex-col gap-2.5 w-full px-2">
            <div className="flex items-center justify-between border-b border-border/40 pb-1.5">
              <span className="text-[9px] font-normal font-mono tracking-wider text-muted uppercase">CRITICAL GAPS</span>
              <span className="font-mono font-normal text-danger bg-danger/10 px-1.5 py-0.5 rounded leading-none text-xs">
                {blocking}
              </span>
            </div>
            <div className="flex items-center justify-between border-b border-border/40 pb-1.5">
              <span className="text-[9px] font-normal font-mono tracking-wider text-muted uppercase">ADVISORIES</span>
              <span className="font-mono font-normal text-warning bg-warning/10 px-1.5 py-0.5 rounded leading-none text-xs">
                {warnings}
              </span>
            </div>
            <div className="flex items-center justify-between pt-0.5">
              <span className="text-[9px] font-normal font-mono tracking-wider text-muted uppercase">RUN STATUS</span>
              <span className={cn("font-mono font-normal px-2 py-0.5 rounded text-[10px] leading-none uppercase border border-border/60 bg-background-alt shadow-sm", toneClass(statusTone(job?.status)))}>
                {job?.status ?? 'pending'}
              </span>
            </div>
          </div>
        </div>

        {/* Dimension scores grid */}
        <div className="min-w-0 p-5 flex flex-col justify-center">
          {gateApplied ? (
            <div className="border-danger/30 bg-danger/5 text-danger mb-4 rounded-[var(--radius-md)] border px-3 py-2.5 text-xs flex items-center gap-2.5 animate-pulse">
              <ShieldAlert className="size-4 shrink-0" />
              <div className="font-semibold leading-snug">
                Discovery Blocked: Agents cannot locate this store definition. Expose dev.ucp.shopping manifest service catalog endpoints.
              </div>
            </div>
          ) : null}

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {report?.dimension_scores.map((dimension) => (
              <DimensionScoreCard
                key={dimension.dimension_id}
                dimension={dimension}
                blocked={gateApplied && dimension.dimension_id !== 'D-UCP1'}
              />
            )) ?? (
                <div className="col-span-full py-8">
                  <DataRegionEmpty
                    title="Awaiting Analytics Execution"
                    description="Supply a target domain and launch a compliance audit to run semantic scoring."
                  />
                </div>
              )}
          </div>
        </div>
      </div>
    </section>
  );
}

export function UcpDimensionTable({
  report,
  loading,
}: Readonly<{ report: UcpAuditReport | null; loading: boolean }>) {
  if (loading) {
    return (
      <TableSurface contentClassName="min-h-[280px]">
        <DataRegionLoading count={7} />
      </TableSurface>
    );
  }

  return (
    <TableSurface contentClassName="min-h-[280px]">
      <header className="border-divider flex items-center justify-between gap-3 border-b px-4 py-3 bg-background/25">
        <div>
          <h2 className="text-xs font-bold font-sans tracking-widest text-muted uppercase">DETAILED DIMENSION METRICS</h2>
          <p className="type-caption text-muted mt-0.5">Determined capabilities of the target store against automated crawlers.</p>
        </div>
        {report ? (
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-normal font-mono text-muted uppercase">CAPABILITY STICKER:</span>
            <Badge tone={badgeTone(scoreTone(report.overall_score))} className="font-normal">{report.overall_score}/100 INDEX</Badge>
          </div>
        ) : null}
      </header>

      {report ? (
        <div className="divide-divider divide-y bg-background/5">
          {report.dimension_scores.map((dimension) => {
            const meta = DIMENSION_META[dimension.dimension_id] ?? {
              label: dimension.dimension_id,
              subtitle: '',
              desc: '',
            };
            const findings = dimension.findings.map((finding, index) =>
              normalizeFinding(finding, index),
            );

            return (
              <article
                key={dimension.dimension_id}
                className="grid gap-6 px-6 py-6 lg:grid-cols-[300px_1fr] hover:bg-background/10 transition-colors"
              >
                <div className="pr-4 border-b pb-4 lg:border-b-0 lg:pb-0 lg:border-r lg:border-divider/40 flex flex-col justify-start">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="font-mono text-[10px] font-normal text-muted bg-background px-2 py-0.5 border border-border/80 rounded">
                      {dimension.dimension_id}
                    </span>
                    <Badge tone={badgeTone(dimension.status)} className="scale-90 font-mono font-normal text-[9px]">
                      {dimension.status}
                    </Badge>
                  </div>
                  <h3 className="mt-1 font-normal text-foreground text-[14px] leading-snug">{meta.label}</h3>
                  <p className="text-[11.5px] text-muted mt-2 leading-relaxed whitespace-normal pr-2">{meta.desc}</p>
                </div>

                <div className="min-w-0 flex flex-col justify-center lg:pl-4">
                  <div className="mb-3.5 flex flex-wrap items-center gap-2">
                    <ScoreBadge score={dimension.score} />
                    <span className="type-caption text-secondary font-normal text-[11px] uppercase tracking-wider">{meta.subtitle}</span>
                  </div>

                  {findings.length ? (
                    <ul className="grid gap-2.5 max-w-[760px] w-full min-w-0">
                      {findings.map((finding) => (
                        <li
                          key={finding.id}
                          className="border-border/50 bg-background/20 hover:bg-background/40 rounded-[var(--radius-md)] border p-4.5 flex items-start gap-3 transition-colors shadow-sm w-full min-w-0"
                        >
                          <AlertTriangle className={cn(
                            "size-4 shrink-0 mt-0.5",
                            finding.severity === 'blocking' ? "text-danger" : "text-warning"
                          )} />
                          <div className="min-w-0 flex-1">
                            <div className="text-[13px] font-normal text-foreground leading-relaxed">{finding.description}</div>
                            <FindingEvidence finding={finding} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="flex items-center gap-2.5 border border-success/20 bg-success/5 rounded-[var(--radius-md)] p-3.5 text-xs text-success max-w-[760px] w-full">
                      <Check className="size-4 shrink-0 text-success" />
                      <span className="font-semibold text-[12.5px]">Compliant capability. Ready for autonomous agent integrations.</span>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <DataRegionEmpty title="Ready for analytics report" description="Awaiting audit execution run to generate capabilities schema analysis." />
      )}
    </TableSurface>
  );
}

export function UcpFindingsPanel({ report }: Readonly<{ report: UcpAuditReport | null }>) {
  const findings = useNormalizedFindings(report);
  const critical = findings.filter((finding) => finding.severity === 'blocking');
  const high = findings.filter((finding) => finding.severity !== 'blocking');

  return (
    <div className="grid gap-5">
      <FindingsTable
        title="Critical Vulnerabilities"
        description="Core architecture blocks preventing autonomous agent discovery or transactions."
        findings={critical}
        empty="No critical blocking vulnerabilities found."
        report={report}
      />
      <FindingsTable
        title="Diagnostic Advisories"
        description="Recommended schema improvements to enhance item discovery accuracy."
        findings={high}
        empty="No warning or advisory recommendations."
        report={null}
      />
    </div>
  );
}

export function UcpAgentViewPanel({ report }: Readonly<{ report: UcpAuditReport | null }>) {
  const samples = getAgentSamples(report);
  const [activeIndex, setActiveIndex] = useState(0);
  const activeSample = samples[activeIndex] ?? null;
  const d7 = report?.dimension_scores.find((dimension) => dimension.dimension_id === 'D-UCP7');
  const d7Findings = (d7?.findings ?? []).map((finding, index) => normalizeFinding(finding, index));

  return (
    <TableSurface>
      <header className="border-divider flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 bg-background/25">
        <div>
          <h2 className="text-xs font-bold font-sans tracking-widest text-muted uppercase">AGENT VIEW VS. HUMAN VIEW (D-UCP7)</h2>
          <p className="type-caption text-muted mt-0.5">
            Compares crawler parsed JSON-LD metadata fields against rendered visible browser facts.
          </p>
        </div>
        {d7 ? (
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-normal font-mono text-muted uppercase">D-UCP7 SCORE:</span>
            <ScoreBadge score={d7.score} />
          </div>
        ) : null}
      </header>

      {activeSample ? (
        <div className="grid gap-0">
          {/* Sample Product URL Tabs */}
          <div className="border-divider flex gap-1.5 overflow-x-auto border-b px-4 py-2 bg-background/10">
            {samples.map((sample, index) => (
              <button
                key={sample.url}
                type="button"
                onClick={() => setActiveIndex(index)}
                className={cn(
                  'rounded-[var(--radius-md)] px-3 py-2 text-left transition-all border cursor-pointer flex items-center justify-between gap-3 min-w-[200px]',
                  index === activeIndex
                    ? 'bg-panel border-border shadow-sm text-foreground'
                    : 'text-muted border-transparent hover:bg-panel/50 hover:text-foreground'
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="block text-[11px] font-mono truncate">{pathLabel(sample.url)}</span>
                    <a
                      href={sample.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted hover:text-accent p-0.5 rounded transition-colors shrink-0 inline-flex items-center justify-center"
                      onClick={(e) => e.stopPropagation()}
                      title="Open page in new tab"
                    >
                      <ExternalLink className="size-3 shrink-0" />
                    </a>
                  </div>
                  <span className="mt-0.5 block text-[10px] text-muted">{Math.round(sample.fidelity_score * 100)}% structural fidelity</span>
                </div>
                <div className="shrink-0">
                  <Badge tone={badgeTone(scoreTone(Math.round(sample.fidelity_score * 100)))} className="scale-90">
                    {Math.round(sample.fidelity_score * 100)}
                  </Badge>
                </div>
              </button>
            ))}
          </div>

          {/* Diff View Column Terminals */}
          <div className="grid lg:grid-cols-2 divide-x divide-divider">
            <ViewColumn
              title="HTTP Agent Payload"
              subtitle="Structured schema metadata (JSON-LD & OpenGraph)"
              icon="agent"
              values={activeSample.agent_extracted}
              missing={activeSample.missing_in_agent_view}
            />
            <ViewColumn
              title="Browser Human View"
              subtitle="Rendered interactive page elements (DOM content)"
              icon="human"
              values={activeSample.human_visible}
              missing={[]}
              highlightKeys={activeSample.missing_in_agent_view}
            />
          </div>

          {/* Tokens breakdown footer */}
          <div className="border-divider border-t px-4 py-4 bg-background/15 grid gap-4 md:grid-cols-2">
            <div className="border border-danger/10 bg-danger/5 rounded-[var(--radius-lg)] p-3">
              <h3 className="text-xs font-normal text-danger flex items-center gap-1.5 mb-2 uppercase font-sans">
                <AlertTriangle className="size-3.5" />
                Missing from agent metadata
              </h3>
              <TokenList items={activeSample.missing_in_agent_view} tone="danger" empty="Perfect alignment. Zero missing visible fields." />
            </div>

            <div className="border border-accent/10 bg-accent-subtle/5 rounded-[var(--radius-lg)] p-3">
              <h3 className="text-xs font-normal text-accent flex items-center gap-1.5 mb-2 uppercase font-sans">
                <Info className="size-3.5" />
                Agent-only metadata fields
              </h3>
              <TokenList items={activeSample.agent_only_signals} tone="accent" empty="No backend-only attributes declared." />
            </div>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 px-4 py-5 lg:grid-cols-[1fr_1fr]">
          <div className="border-border bg-background/25 rounded-[var(--radius-md)] border p-4">
            <div className="mb-3 flex items-center gap-2">
              <EyeOff className="text-muted size-4" />
              <h3 className="text-sm font-semibold">Fidelity delta details pending</h3>
            </div>
            <p className="type-body-sm text-muted">
              Enable the <span className="text-foreground font-normal">Agent Delta</span> scanner option and trigger an audit to map HTTP-extracted JSON data directly against browser-rendered parameters.
            </p>
          </div>

          <div className="border-border bg-background/25 rounded-[var(--radius-md)] border p-4">
            <div className="mb-3 flex items-center gap-2">
              <Eye className="text-muted size-4" />
              <h3 className="text-sm font-normal">Active D-UCP7 Diagnostics</h3>
            </div>
            {d7Findings.length ? (
              <ul className="grid gap-2">
                {d7Findings.map((finding) => (
                  <li key={finding.id} className="text-xs flex gap-2 items-start">
                    <span className="text-danger font-normal shrink-0">•</span>
                    <div>
                      <span className="text-foreground font-normal">{finding.description}</span>
                      <p className="text-[10px] text-muted mt-0.5">Required Action: {finding.fix}</p>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="type-body-sm text-muted">No visual mismatches detected on this run.</p>
            )}
          </div>
        </div>
      )}
    </TableSurface>
  );
}

export function UcpFixSequence({ report }: Readonly<{ report: UcpAuditReport | null }>) {
  const findings = useNormalizedFindings(report);
  const storageKey = report?.job_id ? `ucp-fix-sequence-${report.job_id}` : null;

  const [done, setDone] = useState<Record<string, boolean>>(() => {
    if (!storageKey || typeof window === 'undefined') return {};
    try {
      return JSON.parse(window.localStorage.getItem(storageKey) ?? '{}') as Record<string, boolean>;
    } catch {
      return {};
    }
  });

  const ordered = [...findings].sort((a, b) => impactRank(a.impact) - impactRank(b.impact));
  const doneCount = ordered.filter(f => done[f.id]).length;
  const progressPercent = ordered.length ? Math.round((doneCount / ordered.length) * 100) : 0;

  function toggle(id: string) {
    const next = { ...done, [id]: !done[id] };
    setDone(next);
    if (storageKey && typeof window !== 'undefined') {
      window.localStorage.setItem(storageKey, JSON.stringify(next));
    }
  }

  function exportPlan() {
    const lines = ordered.map((finding, index) => {
      const checked = done[finding.id] ? 'x' : ' ';
      return `- [${checked}] ${index + 1}. [${finding.dimension}] ${finding.action} (${finding.effort}, Impact: ${finding.impact})\n   ↳ Fix guidance: ${finding.fix}`;
    });

    const content = `# UCP Architecture Action Plan\n\nTarget Domain: ${(report?.report_json?.domain as string) ?? 'Audit Store'}\nOverall Compliance: ${report?.overall_score ?? 0}/100\nCompleted Items: ${doneCount}/${ordered.length} (${progressPercent}%)\n\n## Action Items\n\n${lines.join('\n\n')}\n`;

    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    const domain = typeof report?.report_json?.domain === 'string' ? report.report_json.domain : '';
    const fallback = new Date().toISOString().replace(/[:.]/g, '-');
    const rawFilenameBase = report?.job_id ? String(report.job_id) : domain || fallback;
    const filenameBase = rawFilenameBase.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || fallback;
    anchor.href = url;
    anchor.download = `ucp-repair-roadmap-${filenameBase}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <TableSurface>
      <header className="border-divider flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 bg-background/25">
        <div>
          <h2 className="text-xs font-bold font-sans tracking-widest text-muted uppercase">REPAIR ACTION ROADMAP</h2>
          <p className="type-caption text-muted mt-0.5">Step-by-step checklist ordered by impact. Share this with development teams.</p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={exportPlan}
          disabled={!ordered.length}
          className="h-8 border-border bg-panel text-foreground cursor-pointer flex gap-1.5 items-center"
        >
          <Download className="size-3.5" />
          Export action plan
        </Button>
      </header>

      {ordered.length ? (
        <div className="flex flex-col gap-0 divide-y divide-divider">
          {/* Progress Tracker bar */}
          <div className="px-4 py-3 bg-background/10 flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <CheckSquare className="size-4 text-success" />
              <span className="text-xs font-normal text-foreground font-mono">ROADMAP PROGRESS:</span>
              <span className="text-xs font-mono bg-background border border-border px-1.5 py-0.5 rounded text-success font-normal">
                {doneCount} of {ordered.length} fixed ({progressPercent}%)
              </span>
            </div>

            <div className="w-full md:w-48 bg-border h-2 rounded-full overflow-hidden shrink-0">
              <div
                className="bg-success h-full transition-all duration-500 rounded-full"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          <ol className="divide-divider divide-y">
            {ordered.map((finding, index) => {
              const isChecked = done[finding.id];
              return (
                <li
                  key={finding.id}
                  className={cn(
                    "grid gap-3 px-4 py-3.5 sm:grid-cols-[auto_1fr_auto] sm:items-start transition-all",
                    isChecked ? "bg-background/10 opacity-70" : "hover:bg-background/20"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggle(finding.id)}
                    className={cn(
                      'border-border flex size-5 items-center justify-center rounded-[var(--radius-sm)] border transition-all cursor-pointer mt-0.5',
                      isChecked ? 'bg-success border-success text-white' : 'bg-background hover:border-accent',
                    )}
                    aria-label={`Toggle action state`}
                  >
                    {isChecked ? <Check className="size-3.5" /> : null}
                  </button>

                  <div className="min-w-0">
                    <div className={cn(
                      "text-xs font-semibold flex items-center gap-2 flex-wrap text-foreground",
                      isChecked && "line-through text-muted"
                    )}>
                      <span className="text-secondary font-mono">{index + 1}.</span>
                      <span className="font-mono text-[10px] bg-background/80 border border-border px-1.5 rounded leading-none py-0.5">
                        {finding.dimension}
                      </span>
                      <span>{finding.action}</span>
                    </div>
                    <p className={cn("text-[11px] text-muted mt-1 leading-relaxed", isChecked && "text-muted/60")}>
                      {finding.fix}
                    </p>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 self-center">
                    <Badge tone={finding.impact === 'critical' ? 'danger' : finding.impact === 'high' ? 'warning' : 'neutral'}>
                      {finding.impact}
                    </Badge>
                    <Badge tone="neutral" className="font-mono text-[9px]">{finding.effort}</Badge>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      ) : (
        <div className="py-8">
          <DataRegionEmpty title="No repairs found" description="A clean run has been executed. No structured data corrections requested." />
        </div>
      )}
    </TableSurface>
  );
}

export function UcpHistoryList({
  jobs,
  activeId,
  onSelect,
}: Readonly<{
  jobs: UcpAuditJob[];
  activeId: number | null;
  onSelect: (job: UcpAuditJob) => void;
}>) {
  return (
    <TableSurface>
      <header className="border-divider border-b px-4 py-3 bg-background/25">
        <h2 className="text-xs font-bold font-sans tracking-widest text-muted uppercase">AUDIT HISTORY ARCHIVE</h2>
      </header>

      {jobs.length ? (
        <div className="divide-divider divide-y max-h-[460px] overflow-y-auto">
          {jobs.map((job) => {
            const isActive = job.id === activeId;
            const score = Number(job.summary?.overall_score ?? 0);
            return (
              <button
                key={job.id}
                type="button"
                aria-pressed={isActive}
                onClick={() => onSelect(job)}
                className={cn(
                  'hover:bg-background/30 grid w-full gap-2 px-4 py-3 text-left transition-all sm:grid-cols-[1fr_auto] cursor-pointer relative pl-5',
                  isActive && 'bg-accent-subtle/50',
                )}
              >
                {/* Active Indicator bar */}
                {isActive && (
                  <div className="absolute top-0 left-0 bottom-0 w-[3px] bg-accent" />
                )}

                <div className="min-w-0 flex flex-col justify-between">
                  <div className="text-xs font-normal text-foreground truncate font-mono">{job.domain}</div>
                  <div className="text-[10px] text-muted mt-1.5 flex items-center gap-1 font-mono">
                    <span>#{job.id}</span>
                    <span>•</span>
                    <span>{new Date(job.created_at).toLocaleString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0 self-center">
                  <Badge tone={badgeTone(job.status)} className="scale-90">
                    {job.status}
                  </Badge>

                  {job.status === 'complete' && (
                    <Badge tone={badgeTone(scoreTone(score))} className="scale-90 font-mono">
                      {score}
                    </Badge>
                  )}
                  <ChevronRight className="text-muted size-3 shrink-0" />
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="py-8">
          <DataRegionEmpty title="Archive Empty" description="Your generated UCP audit runs will queue up in this timeline history list." />
        </div>
      )}
    </TableSurface>
  );
}

function FindingsTable({
  title,
  description,
  findings,
  empty,
  report,
}: Readonly<{
  title: string;
  description: string;
  findings: NormalizedFinding[];
  empty: string;
  report: UcpAuditReport | null;
}>) {
  return (
    <TableSurface>
      <header className="border-divider flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 bg-background/25">
        <div>
          <h2 className="text-xs font-bold font-sans tracking-widest text-muted uppercase">{title}</h2>
          <p className="type-caption text-muted mt-0.5">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {report ? (
            <>
              <Button asChild variant="secondary" size="sm" className="h-7 text-[11px] border-border bg-panel text-foreground cursor-pointer flex gap-1 items-center">
                <a href={api.exportUcpAuditJson(report.job_id)} target="_blank" rel="noreferrer">
                  <Download className="size-3" />
                  JSON
                </a>
              </Button>
              <Button asChild variant="secondary" size="sm" className="h-7 text-[11px] border-border bg-panel text-foreground cursor-pointer flex gap-1 items-center">
                <a href={api.exportUcpAuditMarkdown(report.job_id)} target="_blank" rel="noreferrer">
                  <Download className="size-3" />
                  Markdown
                </a>
              </Button>
            </>
          ) : null}
        </div>
      </header>

      {findings.length ? (
        <div className="overflow-x-auto">
          <Table className="min-w-[980px]">
            <TableHeader>
              <TableRow className="bg-background/10 hover:bg-background/10 border-b border-divider/60">
                <TableHead className="w-[110px] text-xs font-bold font-mono py-3.5">Severity</TableHead>
                <TableHead className="w-[110px] text-xs font-bold font-mono py-3.5">Dimension</TableHead>
                <TableHead className="text-xs font-bold font-mono py-3.5">Structural Gap</TableHead>
                <TableHead className="w-[140px] text-xs font-bold font-mono py-3.5 text-left">Affected</TableHead>
                <TableHead className="w-[120px] text-xs font-bold font-mono py-3.5">Difficulty</TableHead>
                <TableHead className="text-xs font-bold font-mono py-3.5">Corrective Action Guidance</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {findings.map((finding) => (
                <TableRow key={finding.id} className="hover:bg-background/15 border-b border-divider/60">
                  <TableCell className="py-4 align-top">
                    <Badge tone={badgeTone(finding.severity)} className="scale-90 font-mono font-normal">
                      {finding.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-4 align-top">
                    <span className="font-mono text-[10px] font-normal text-muted bg-background border border-border px-1.5 py-0.5 rounded">
                      {finding.dimension}
                    </span>
                  </TableCell>
                  <TableCell className="py-4 align-top">
                    <div className="max-w-[400px] whitespace-normal font-normal text-[13px] leading-relaxed text-foreground/95">
                      {finding.description}
                    </div>
                    <FindingEvidence finding={finding} />
                  </TableCell>
                  <TableCell className="py-4 align-top text-left font-mono text-xs font-normal whitespace-nowrap text-secondary/90">
                    {affectedLabel(finding)}
                  </TableCell>
                  <TableCell className="py-4 align-top">
                    <Badge tone="neutral" className="text-[10px] font-mono leading-none">{finding.effort}</Badge>
                  </TableCell>
                  <TableCell className="py-4 align-top">
                    <div className="max-w-[420px] whitespace-normal font-normal text-[13px] leading-relaxed text-muted-foreground">
                      {finding.fix}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="py-8">
          <DataRegionEmpty title={empty} description="Checks complete. This section compiles when a completed compliance report is parsed." />
        </div>
      )}
    </TableSurface>
  );
}

function DimensionScoreCard({
  dimension,
  blocked,
}: Readonly<{
  dimension: UcpAuditReport['dimension_scores'][number];
  blocked: boolean;
}>) {
  const meta = DIMENSION_META[dimension.dimension_id] ?? {
    label: dimension.dimension_id,
    subtitle: '',
    desc: '',
  };
  return (
    <div
      className={cn(
        'border-border bg-background/25 relative min-h-[180px] rounded-[var(--radius-md)] border p-5 flex flex-col justify-between transition-all duration-300 hover:scale-[1.02] hover:shadow-md hover:border-accent/60',
        blocked && 'opacity-35 select-none pointer-events-none',
      )}
    >
      {blocked ? (
        <div className="absolute inset-0 bg-background/10 backdrop-blur-[0.5px] rounded-[var(--radius-md)] flex items-center justify-center z-10">
          <span className="text-danger rotate-12 font-mono text-xs font-black tracking-widest border border-danger/45 bg-background/90 px-2 py-0.5 rounded shadow">
            BLOCKED
          </span>
        </div>
      ) : null}

      <div className="flex items-start justify-between gap-3">
        <ScoreRing score={dimension.score} size={70} stroke={8} label={dimension.dimension_id} compact />
        {dimension.findings.length ? (
          <Badge tone="danger" className="animate-pulse font-mono font-normal text-[9px]">
            {dimension.findings.length} gaps
          </Badge>
        ) : (
          <Badge tone="success" className="scale-90 font-mono font-normal text-[9px]">READY</Badge>
        )}
      </div>

      <div className="mt-3.5">
        <div className="text-[13px] font-normal text-foreground leading-snug">{meta.label}</div>
        <p className="text-[11px] text-muted leading-normal mt-1.5 whitespace-normal">{meta.subtitle}</p>
        <div className="mt-3.5 flex items-center justify-between">
          <Badge tone={badgeTone(dimension.status)} className="scale-90 font-mono font-normal">
            {dimension.status}
          </Badge>
          <span className="text-[9px] font-mono text-muted uppercase font-normal tracking-wide">{dimension.dimension_id}</span>
        </div>
      </div>
    </div>
  );
}

function ScoreRing({
  score,
  size,
  stroke,
  label,
  compact = false,
}: Readonly<{ score: number; size: number; stroke: number; label: string; compact?: boolean }>) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.max(0, Math.min(100, score)) / 100) * circumference;
  return (
    <div className="relative grid place-items-center shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Underlay trace ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="stroke-border"
          strokeWidth={stroke}
        />
        {/* Animated Score ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className={ringClass(score)}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 800ms ease-out' }}
        />
      </svg>

      <div className="absolute text-center select-none">
        <div className={cn('font-mono font-bold tabular-nums text-foreground tracking-tighter leading-none', compact ? 'text-sm font-semibold' : 'text-3xl')}>
          {score}
        </div>
        {!compact && (
          <div className="text-[9px] font-mono font-bold tracking-wider text-muted mt-0.5 uppercase leading-none">
            /100
          </div>
        )}
      </div>
    </div>
  );
}

function ViewColumn({
  title,
  subtitle,
  icon,
  values,
  missing,
  highlightKeys = [],
  isJson = false,
}: Readonly<{
  title: string;
  subtitle: string;
  icon: 'agent' | 'human';
  values: Record<string, unknown>;
  missing: string[];
  highlightKeys?: string[];
  isJson?: boolean;
}>) {
  const rows = Object.entries(values);
  return (
    <section className="p-4 flex flex-col bg-background/5 min-w-0">
      <div className="mb-4 flex items-center gap-2">
        <div className={cn(
          "size-7 rounded-lg flex items-center justify-center border",
          icon === 'agent' ? "bg-accent-subtle/10 border-accent/25" : "bg-success/10 border-success/25"
        )}>
          {icon === 'agent' ? (
            <EyeOff className="text-accent size-4" />
          ) : (
            <Eye className="text-success size-4" />
          )}
        </div>
        <div>
          <h3 className="text-xs font-bold text-foreground leading-none">{title}</h3>
          <p className="text-[10px] text-muted mt-1 leading-none">{subtitle}</p>
        </div>
      </div>

      <div className="flex-1 font-mono text-[11px] max-h-[360px] overflow-auto bg-zinc-950 p-3 rounded-lg border border-zinc-800 text-zinc-100 w-full min-w-0" style={{ fontSynthesis: 'none' }}>
        {isJson ? (
          Object.keys(values).length > 0 ? (
            <pre
              className="font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all"
              dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(JSON.stringify(values, null, 2)) }}
            />
          ) : (
            <div className="text-center py-6 text-zinc-500 font-sans text-xs flex flex-col items-center justify-center gap-1.5">
              <Info className="size-5 text-zinc-600" />
              <span>No JSON data available for this sample.</span>
            </div>
          )
        ) : (
          <div className="flex flex-col gap-1.5 w-full">
            {rows.map(([key, value]) => {
              const highlighted = highlightKeys.includes(key);
              const rawVal = stringValue(value) || '""';
              return (
                <div
                  key={key}
                  className={cn(
                    'px-2 py-1 rounded transition-colors w-full min-w-0',
                    highlighted
                      ? 'bg-red-950/40 text-red-200 border-l-2 border-red-500 font-light'
                      : 'bg-zinc-900/50 hover:bg-zinc-800/50 text-zinc-300'
                  )}
                >
                  <div className="flex items-center justify-between gap-4 w-full min-w-0">
                    <span className={cn("shrink-0 font-light max-w-[45%] truncate", highlighted ? "text-red-300 font-normal" : "text-zinc-400")}>
                      {key}:
                    </span>
                    <span
                      className={cn(
                        "truncate font-light max-w-[55%] select-all cursor-help border-b border-dashed pb-0.5 transition-colors",
                        highlighted
                          ? "text-red-100 border-red-700/40 hover:border-red-500"
                          : "text-zinc-100 border-zinc-700/50 hover:border-zinc-500"
                      )}
                      title={rawVal}
                    >
                      {rawVal}
                    </span>
                  </div>
                </div>
              );
            })}

            {missing.map((key) => (
              <div
                key={key}
                className="bg-red-950/40 text-red-200 border-l-2 border-red-500 font-light px-2 py-1.5 rounded animate-pulse w-full min-w-0"
              >
                <div className="flex items-center justify-between gap-4 w-full min-w-0">
                  <span className="flex items-center gap-1 shrink-0 font-normal text-red-300 max-w-[45%] truncate">
                    <X className="size-3 text-red-400 shrink-0" />
                    {key}:
                  </span>
                  <span className="text-[10px] italic font-normal text-red-400 shrink-0">Missing from agent metadata</span>
                </div>
              </div>
            ))}

            {!rows.length && !missing.length ? (
              <div className="text-center py-6 text-zinc-500 font-sans text-xs flex flex-col items-center justify-center gap-1.5">
                <Info className="size-5 text-zinc-600" />
                <span>No data fields mapped for this page sample.</span>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function TokenList({
  items,
  tone,
  empty,
}: Readonly<{ items: string[]; tone: 'danger' | 'accent'; empty: string }>) {
  if (!items.length) {
    return (
      <div className="text-muted text-[11px] font-medium py-1">
        ✓ {empty}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item}
          className={cn(
            'rounded-[4px] px-2 py-0.5 font-mono text-[10px] font-light border',
            tone === 'danger'
              ? 'bg-danger/5 border-danger/20 text-danger'
              : 'bg-accent-subtle/10 border-accent/20 text-accent',
          )}
          style={{ fontSynthesis: 'none' }}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function MiniStat({
  label,
  value,
  tone,
}: Readonly<{ label: string; value: number | string; tone: 'success' | 'warning' | 'danger' | 'neutral' }>) {
  return (
    <div className="border-border bg-background/25 rounded-[var(--radius-md)] border p-2 flex flex-col justify-between min-w-[70px]">
      <div className="text-[9px] font-bold font-mono tracking-wider text-muted uppercase leading-none">{label}</div>
      <div className={cn('mt-1.5 font-mono text-xs font-bold leading-none tabular-nums truncate', toneClass(tone))}>
        {value}
      </div>
    </div>
  );
}

function ScoreBadge({ score }: Readonly<{ score: number }>) {
  return <Badge tone={badgeTone(scoreTone(score))}>{score}</Badge>;
}

function useNormalizedFindings(report: UcpAuditReport | null) {
  return useMemo(
    () => (report?.findings ?? []).map((finding, index) => normalizeFinding(finding, index)),
    [report],
  );
}

function normalizeFinding(finding: Record<string, unknown>, index: number): NormalizedFinding {
  const code = String(finding.code ?? 'unknown_finding');
  const dimension = String(finding.dimension_id ?? finding.dimension ?? '');
  const copy = FINDING_COPY[code] ?? {
    description: String(finding.message || code),
    fix: 'Inspect the exported JSON and update the structured data source for this dimension.',
    effort: 'review',
    action: `Resolve ${code}`,
    impact: 'medium' as const,
  };
  return {
    id: `${dimension}-${code}-${index}`,
    code,
    dimension,
    severity: String(finding.severity ?? 'info'),
    description: String(finding.message || copy.description),
    fix: copy.fix,
    effort: copy.effort,
    action: copy.action,
    impact: copy.impact,
    affected: Number(finding.affected_count ?? 0),
    countKind: String(finding.count_kind ?? 'items'),
    affectedUrls: Array.isArray(finding.affected_urls)
      ? finding.affected_urls.map((item) => String(item)).filter(Boolean)
      : [],
    evidence: Array.isArray(finding.evidence)
      ? finding.evidence.filter(
        (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object',
      )
      : [],
  };
}

function affectedLabel(finding: NormalizedFinding) {
  if (finding.countKind === 'domain_check') return 'Domain-level';
  if (!finding.affected) return '--';
  if (finding.countKind === 'field_instances') return `${finding.affected} field gaps`;
  if (finding.countKind === 'attribute_gaps') return `${finding.affected} attribute gaps`;
  if (finding.countKind === 'taxonomy_gaps') return `${finding.affected} taxonomy gaps`;
  if (finding.countKind === 'urls') return `${finding.affected} URLs`;
  return `${finding.affected} items`;
}

function FindingEvidence({ finding }: Readonly<{ finding: NormalizedFinding }>) {
  const rows = finding.evidence.length
    ? finding.evidence
    : finding.affectedUrls.map((url) => ({ url }));
  if (!rows.length) return null;
  return (
    <details className="mt-2 text-[10px] font-normal text-muted group">
      <summary className="cursor-pointer font-mono text-[10px] text-secondary hover:text-accent select-none list-none [&::-webkit-details-marker]:hidden flex items-center gap-1.5 py-0.5">
        <span className="text-[7px] text-muted-foreground/60 transition-transform duration-200 group-open:rotate-90">▶</span>
        <span>View evidence</span>
      </summary>
      <div className="mt-2 grid gap-2 pl-3 border-l border-border/40">
        {rows.slice(0, 8).map((row, index) => (
          <div key={`${String(row.url ?? index)}-${index}`} className="rounded border border-border/50 bg-background/20 p-2 shadow-sm">
            {'url' in row ? (
              <div className="break-all font-mono text-[10px] text-foreground font-normal pb-1 border-b border-border/30 mb-1 flex items-center justify-between gap-2">
                <a
                  href={String(row.url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-accent transition-colors flex items-center gap-1.5 min-w-0"
                  title="Open live URL"
                >
                  <span className="truncate">{String(row.url)}</span>
                  <ExternalLink className="size-3 shrink-0 text-muted" />
                </a>
              </div>
            ) : null}
            <EvidenceFields row={row} />
          </div>
        ))}
      </div>
    </details>
  );
}

function EvidenceFields({ row }: Readonly<{ row: Record<string, unknown> }>) {
  const fieldRows = Object.entries(row).filter(([key]) => key !== 'url');
  if (!fieldRows.length) return null;
  return (
    <div className="mt-1 flex flex-col gap-1 w-full min-w-0">
      {fieldRows.map(([key, value]) => (
        <div key={key} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] min-w-0 w-full">
          <span className="font-mono text-muted/80 font-normal shrink-0 uppercase tracking-wider text-[8.5px]">
            {key}:
          </span>
          <span className="font-mono text-secondary break-all font-normal">
            {formatEvidenceValue(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function formatEvidenceValue(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ');
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (value && typeof value === 'object') return JSON.stringify(value);
  return String(value ?? '');
}

function getAgentSamples(report: UcpAuditReport | null): AgentViewSample[] {
  const raw = report?.report_json?.agent_view_samples;
  if (!Array.isArray(raw)) return [];
  return raw.filter(isAgentSample);
}

function isAgentSample(value: unknown): value is AgentViewSample {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<AgentViewSample>;
  return (
    typeof item.url === 'string' &&
    typeof item.agent_extracted === 'object' &&
    typeof item.human_visible === 'object' &&
    Array.isArray(item.missing_in_agent_view) &&
    Array.isArray(item.agent_only_signals)
  );
}

function scoreTone(score: number) {
  if (score >= 80) return 'success';
  if (score >= 50) return 'warning';
  return 'danger';
}

function statusTone(status?: string) {
  if (status === 'complete') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'queued' || status === 'running') return 'warning';
  return 'neutral';
}

function badgeTone(value: string) {
  if (value === 'success' || value === 'pass' || value === 'complete') return 'success';
  if (value === 'warning' || value === 'queued' || value === 'running') return 'warning';
  if (value === 'danger' || value === 'fail' || value === 'failed' || value === 'blocking') {
    return 'danger';
  }
  return 'neutral';
}

function toneClass(tone: string) {
  if (tone === 'success') return 'text-success';
  if (tone === 'warning') return 'text-warning';
  if (tone === 'danger') return 'text-danger';
  return 'text-foreground';
}

function ringClass(score: number) {
  if (score >= 80) return 'stroke-success';
  if (score >= 50) return 'stroke-warning';
  return 'stroke-danger';
}

function impactRank(impact: string) {
  if (impact === 'critical') return 0;
  if (impact === 'high') return 1;
  return 2;
}

function pathLabel(url: string) {
  try {
    const parsed = new URL(url);
    return parsed.pathname || url;
  } catch {
    return url;
  }
}

function stringValue(value: unknown) {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value == null) return '';
  return JSON.stringify(value);
}
