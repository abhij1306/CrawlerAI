'use client';

import { type ReactNode, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, CheckSquare, Download, ShieldAlert, Sparkles } from 'lucide-react';

import { DataRegionEmpty, DataRegionLoading, TableSurface } from '../../components/ui/patterns';
import { Badge, Button, Card } from '../../components/ui/primitives';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { cn } from '../../lib/utils';
import type { UcpAuditJob, UcpAuditReport } from '../../lib/api/types';

const DIMENSION_META: Record<string, { label: string; subtitle: string; desc: string }> = {
  'D-AID1': {
    label: 'Structured Markup',
    subtitle: 'Product JSON-LD',
    desc: 'Checks Product JSON-LD, Open Graph product tags, and JSON-LD parse quality.',
  },
  'D-AID2': {
    label: 'Catalog Completeness',
    subtitle: 'Product field coverage',
    desc: 'Checks title, description, price, images, variants, identifiers, and brand coverage.',
  },
  'D-AID3': {
    label: 'Commerce Signals',
    subtitle: 'Offer and policy cues',
    desc: 'Checks structured offers, payment methods, EMI, delivery, and return signals.',
  },
  'D-AID4': {
    label: 'Freshness & Availability',
    subtitle: 'Stock and price alignment',
    desc: 'Checks availability, price freshness, and sampled out-of-stock rate.',
  },
  'D-AID5': {
    label: 'Trust & Social Proof',
    subtitle: 'Rating and review markup',
    desc: 'Checks aggregate ratings, review counts, and review schema shape.',
  },
  'D-AID6': {
    label: 'Local & Discovery',
    subtitle: 'Robots and sitemap signals',
    desc: 'Checks LocalBusiness markup, AI crawler robots rules, and sitemap availability.',
  },
};

const FINDING_COPY: Record<
  string,
  {
    description: string;
    fix: string;
    effort: string;
    action: string;
    impact: 'critical' | 'high' | 'medium';
  }
> = {
  AID1_JSONLD_MISSING: {
    description: 'No JSON-LD structured data was detected on sampled product pages.',
    fix: 'Add schema.org Product JSON-LD to product pages.',
    effort: '2 hours',
    action: 'Add Product JSON-LD',
    impact: 'critical',
  },
  AID1_PRODUCT_TYPE_MISSING: {
    description: 'JSON-LD is present, but Product type is missing.',
    fix: 'Declare @type Product in product JSON-LD.',
    effort: '1 hour',
    action: 'Declare Product type',
    impact: 'critical',
  },
  AID1_OPEN_GRAPH_MISSING: {
    description: 'No Open Graph product signal was detected.',
    fix: 'Add product Open Graph metadata.',
    effort: '1 hour',
    action: 'Add OG product tags',
    impact: 'medium',
  },
  AID1_SCHEMA_INVALID: {
    description: 'One or more JSON-LD blocks could not be parsed.',
    fix: 'Fix malformed JSON-LD syntax.',
    effort: '2 hours',
    action: 'Fix JSON-LD',
    impact: 'medium',
  },
  AID2_TITLE_MISSING: {
    description: 'Product title is missing on sampled pages.',
    fix: 'Expose product title in visible and structured data.',
    effort: '1 hour',
    action: 'Add titles',
    impact: 'critical',
  },
  AID2_PRICE_MISSING: {
    description: 'Product price is missing on sampled pages.',
    fix: 'Expose current price in page markup and extraction output.',
    effort: '2 hours',
    action: 'Add prices',
    impact: 'critical',
  },
  AID2_DESCRIPTION_SHORT: {
    description: 'Product description is missing or too short.',
    fix: 'Add useful product descriptions of at least 100 characters.',
    effort: '2-4 hours',
    action: 'Improve descriptions',
    impact: 'high',
  },
  AID2_IMAGES_MISSING: {
    description: 'Product images are missing.',
    fix: 'Expose primary image URLs in markup.',
    effort: '2 hours',
    action: 'Add images',
    impact: 'high',
  },
  AID2_VARIANTS_MISSING: {
    description: 'Variant, size, or color data is missing.',
    fix: 'Expose available variant choices.',
    effort: '1 sprint',
    action: 'Add variants',
    impact: 'high',
  },
  AID2_IDENTIFIERS_MISSING: {
    description: 'SKU, GTIN, or MPN is missing.',
    fix: 'Add stable product identifiers.',
    effort: '2-4 hours',
    action: 'Add identifiers',
    impact: 'medium',
  },
  AID3_OFFER_MISSING: {
    description: 'No schema.org Offer block was detected.',
    fix: 'Add Offer structured data with price and currency.',
    effort: '2 hours',
    action: 'Add offers',
    impact: 'critical',
  },
  AID3_PAYMENT_METHODS_MISSING: {
    description: 'No payment method signal was detected.',
    fix: 'Expose supported payment methods.',
    effort: '2-4 hours',
    action: 'Add payment signals',
    impact: 'high',
  },
  AID3_EMI_SIGNAL_MISSING: {
    description: 'No EMI or installment signal was detected.',
    fix: 'Expose installment options when supported.',
    effort: '2-4 hours',
    action: 'Add EMI signals',
    impact: 'medium',
  },
  AID3_DELIVERY_ETA_MISSING: {
    description: 'No delivery ETA signal was detected.',
    fix: 'Expose delivery or shipping timing.',
    effort: '2 hours',
    action: 'Add delivery signals',
    impact: 'medium',
  },
  AID3_RETURN_POLICY_MISSING: {
    description: 'No return policy signal was detected.',
    fix: 'Expose return and refund policy details.',
    effort: '2 hours',
    action: 'Add return policy',
    impact: 'medium',
  },
  AID4_AVAILABILITY_MISSING: {
    description: 'No schema.org availability signal was detected.',
    fix: 'Add availability to Offer structured data.',
    effort: '2 hours',
    action: 'Add availability',
    impact: 'critical',
  },
  AID4_PRICE_STALE: {
    description: 'Structured price diverges from visible price by more than 5%.',
    fix: 'Keep structured price aligned with visible DOM price.',
    effort: '2 hours',
    action: 'Fix price freshness',
    impact: 'high',
  },
  AID4_OUT_OF_STOCK_RATE_HIGH: {
    description: 'More than 30% of sampled pages look out of stock.',
    fix: 'Expose alternatives or improve stock state coverage.',
    effort: '1 sprint',
    action: 'Improve stock signals',
    impact: 'medium',
  },
  AID5_RATING_MISSING: {
    description: 'No aggregateRating was detected in structured data.',
    fix: 'Add aggregateRating when review data exists.',
    effort: '2-4 hours',
    action: 'Add ratings',
    impact: 'medium',
  },
  AID5_REVIEW_COUNT_ZERO: {
    description: 'Rating is present but review count is zero.',
    fix: 'Set reviewCount or ratingCount to the displayed review count.',
    effort: '1 hour',
    action: 'Fix review count',
    impact: 'medium',
  },
  AID5_REVIEW_SCHEMA_INVALID: {
    description: 'Review markup is malformed.',
    fix: 'Fix review author and rating fields.',
    effort: '2 hours',
    action: 'Fix reviews',
    impact: 'medium',
  },
  AID6_LOCAL_BUSINESS_MISSING: {
    description: 'No LocalBusiness markup was detected.',
    fix: 'Add LocalBusiness markup for stores or service areas.',
    effort: '2 hours',
    action: 'Add local markup',
    impact: 'medium',
  },
  AID6_ROBOTS_BLOCKING_AI: {
    description: 'robots.txt blocks one or more AI crawlers.',
    fix: 'Review GPTBot and PerplexityBot robots directives.',
    effort: '1 hour',
    action: 'Review robots.txt',
    impact: 'high',
  },
  AID6_SITEMAP_MISSING: {
    description: 'No sitemap.xml was detected.',
    fix: 'Publish sitemap.xml or a sitemap index.',
    effort: '1 hour',
    action: 'Add sitemap',
    impact: 'medium',
  },
  AID_LLM_IDENTITY_UNCLEAR: {
    description: 'AI review could not clearly identify the product purpose and attributes.',
    fix: 'Add plain-language product type, use case, material, fit, and audience details.',
    effort: '2-4 hours',
    action: 'Clarify product identity',
    impact: 'high',
  },
  AID_LLM_VARIANTS_MISSING: {
    description: 'AI review could not infer variant choices from page evidence.',
    fix: 'Expose size, color, fit, and material choices in visible text and structured data.',
    effort: '1 sprint',
    action: 'Clarify variants',
    impact: 'high',
  },
  AID_LLM_VARIANTS_UNRESOLVABLE: {
    description: 'AI review found variant information but could not resolve available choices.',
    fix: 'Make variant labels, availability, and selected-state text explicit for each option.',
    effort: '1 sprint',
    action: 'Resolve variant choices',
    impact: 'high',
  },
  AID_LLM_DESCRIPTION_FLUFF: {
    description: 'AI review judged the description as marketing-heavy and low on product facts.',
    fix: 'Add concrete details such as material, fit, dimensions, use case, care, and constraints.',
    effort: '2-4 hours',
    action: 'Replace vague copy',
    impact: 'high',
  },
  AID_LLM_DESCRIPTION_SHORT: {
    description: 'AI review found too little description evidence to answer buyer questions.',
    fix: 'Add a fuller product description with category-specific attributes and buyer guidance.',
    effort: '2-4 hours',
    action: 'Expand description',
    impact: 'high',
  },
  AID_LLM_INTENT_UNANSWERABLE: {
    description: 'AI review found shopper questions that the page evidence cannot answer.',
    fix: 'Add buyer-facing answers for occasion, fit, care, delivery, and comparison questions.',
    effort: '2-4 hours',
    action: 'Answer shopper intent',
    impact: 'critical',
  },
  AID_LLM_COHERENCE_CONTRADICTION: {
    description: 'AI review found conflicting page signals.',
    fix: 'Align JSON-LD, Open Graph, DOM text, and extracted product fields.',
    effort: '2 hours',
    action: 'Fix signal conflicts',
    impact: 'high',
  },
  AID_LLM_COHERENCE_INCOMPLETE: {
    description: 'AI review found the product story incomplete across page signals.',
    fix: 'Fill missing facts consistently across DOM, structured data, Open Graph, and extracted records.',
    effort: '2-4 hours',
    action: 'Complete signal story',
    impact: 'medium',
  },
  AID_LLM_RECOMMENDATION_LOW_CONFIDENCE: {
    description: 'AI review would not confidently recommend this product for a specific need.',
    fix: 'Add concrete benefits, supported use cases, audience, constraints, and comparison cues.',
    effort: '2-4 hours',
    action: 'Raise recommendation confidence',
    impact: 'high',
  },
  AID_LLM_INSUFFICIENT_EVIDENCE: {
    description: 'AI review could not gather sufficient evidence to evaluate this dimension.',
    fix: 'Ensure page markup exposes enough structured and visible content for AI evaluation.',
    effort: '2-4 hours',
    action: 'Improve page evidence',
    impact: 'medium',
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
  evidence: Array<Record<string, unknown>>;
};

type ContractTransport = {
  service?: string;
  transport?: string;
  endpoint?: string;
  reachable?: boolean;
  negotiated?: boolean;
  profile_required?: boolean;
  status_code?: number;
  error?: string;
  tool_names?: string[];
};

type UcpContract = {
  catalog?: {
    domain?: string;
    pages_crawled?: number;
    sampled_urls?: string[];
    crawl_errors?: string[];
  };
  structured_markup?: {
    product_jsonld_count?: number;
    jsonld_block_count?: number;
    jsonld_parse_errors?: string[];
    open_graph?: Record<string, string>;
  };
  product_records?: Array<Record<string, unknown>>;
  discovery?: {
    robots_directives?: Record<string, string[]>;
    sitemap_found?: boolean;
  };
  ai_assessment?: {
    enabled?: boolean;
    results?: Array<{
      url?: string;
      findings?: Array<Record<string, unknown>>;
      simulated_queries?: Array<{ query?: string; answerable?: boolean; gap?: string }>;
      llm_provider?: string;
      llm_model?: string;
      error?: string;
    }>;
    contradictions?: Array<{
      url?: string;
      flags?: Array<Record<string, unknown>>;
    }>;
  };
  manifest?: {
    found?: boolean;
    valid?: boolean;
    errors?: string[];
    supported_versions?: string[];
    target_version?: string;
    selected_version?: string;
    version_source?: string;
    content_type?: string;
    final_url?: string;
    redirect_chain?: string[];
    discovery_source?: string;
  };
  services?: string[];
  capabilities?: string[];
  missing_required_services?: string[];
  missing_required_capabilities?: string[];
  transports?: ContractTransport[];
  schemas?: Array<{
    url?: string;
    reachable?: boolean;
    valid_json?: boolean;
    schema_valid?: boolean;
    title?: string;
    error?: string;
    status_code?: number;
    content_type?: string;
    groups?: string[];
    field_results?: Record<string, Record<string, boolean>>;
    llm_analysis?: Record<string, unknown>;
  }>;
  payment_handlers?: string[];
};

export function UcpScoreSummary({
  report,
  job,
  loading = false,
}: Readonly<{ report: UcpAuditReport | null; job: UcpAuditJob | null; loading?: boolean }>) {
  const score = report?.overall_score ?? Number(job?.summary?.overall_score ?? 0);
  const findings = useNormalizedFindings(report);
  const blocking = findings.filter((finding) => finding.severity === 'blocking').length;
  const warnings = findings.filter((finding) => finding.severity !== 'blocking').length;
  const gateApplied = Boolean(report?.report_json?.d_ucp1_gate_applied);
  const dUcp1GateMax = Number(report?.report_json?.d_ucp1_gate_max_score ?? 30);

  return (
    <section className="border-border bg-panel overflow-hidden rounded-lg border shadow-sm">
      <div className="grid gap-0 lg:grid-cols-[300px_1fr]">
        <div className="border-divider bg-background/30 relative flex flex-col items-center justify-center border-b p-6 lg:border-r lg:border-b-0">
          <div className="absolute inset-x-0 top-3 flex items-center justify-center gap-1.5">
            <Sparkles className="text-accent size-3 animate-pulse" />
            <span className="type-label-mono">AI DISCOVERABILITY SCORE</span>
          </div>
          {loading && !report ? (
            <LoadingScoreRing size={156} />
          ) : (
            <ScoreRing score={report ? score : 0} size={156} stroke={10} />
          )}
          <div className="mt-4 flex w-full flex-col gap-2.5 px-2">
            <SummaryRow label="Blocking gaps" value={blocking} tone="danger" />
            <SummaryRow label="Warnings" value={warnings} tone="warning" />
            <SummaryRow
              label="Run status"
              value={job?.status ?? 'pending'}
              tone={statusTone(job?.status)}
            />
          </div>
        </div>

        <div className="flex min-w-0 flex-col justify-center p-5">
          {gateApplied ? (
            <div className="border-danger/30 bg-danger/5 text-danger mb-4 flex items-center gap-2.5 rounded-md border px-3 py-2.5">
              <ShieldAlert className="size-4 shrink-0" />
              <div className="leading-snug">
                <p className="type-subheading text-danger">
                  Structured markup blocked - overall score capped at {dUcp1GateMax}.
                </p>
                <p className="type-caption text-danger/75 mt-0.5">
                  Add Product JSON-LD before other signals can fully count.
                </p>
              </div>
            </div>
          ) : null}

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {report?.dimension_scores.map((dimension) => (
              <DimensionScoreCard
                key={dimension.dimension_id}
                dimension={dimension}
                blocked={gateApplied && dimension.dimension_id !== 'D-AID1'}
              />
            )) ?? (
              <div className="col-span-full py-8">
                <DataRegionEmpty
                  title="Awaiting audit"
                  description="Supply a target domain and launch an AI discoverability audit."
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
        <DataRegionLoading count={6} />
      </TableSurface>
    );
  }

  return (
    <TableSurface contentClassName="min-h-[280px]">
      <header className="border-divider bg-background/25 flex items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="type-label-mono">AI DISCOVERABILITY DIMENSIONS</h2>
          <p className="type-caption mt-0.5">
            Score measured against structured markup, catalog completeness, commerce, freshness,
            trust, and discovery signals.
          </p>
        </div>
        {report ? (
          <Badge tone={badgeTone(scoreTone(report.overall_score))} className="font-normal">
            {report.overall_score}/100
          </Badge>
        ) : null}
      </header>

      {report ? (
        <div className="divide-divider bg-background/5 divide-y">
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
                className="hover:bg-background/10 grid gap-6 p-6 transition-colors lg:grid-cols-[300px_1fr]"
              >
                <div className="lg:border-divider/40 flex flex-col justify-start border-b pr-4 pb-4 lg:border-r lg:border-b-0 lg:pb-0">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-foreground bg-background border-border/80 rounded border px-2 py-0.5 font-mono text-xs">
                      {dimension.dimension_id}
                    </span>
                    <Badge tone={badgeTone(dimension.status)} className="scale-90">
                      {dimension.status}
                    </Badge>
                  </div>
                  <h3 className="type-subheading text-foreground mt-1">{meta.label}</h3>
                  <p className="type-caption mt-2 pr-2">{meta.desc}</p>
                </div>

                <div className="flex min-w-0 flex-col justify-center lg:pl-4">
                  <div className="mb-3.5 flex flex-wrap items-center gap-2">
                    <ScoreBadge score={dimension.score} />
                    <span className="type-label text-secondary">{meta.subtitle}</span>
                  </div>

                  {findings.length ? (
                    <ul className="grid w-full max-w-[760px] min-w-0 gap-2.5">
                      {findings.map((finding) => (
                        <li
                          key={finding.id}
                          className="border-border bg-panel flex w-full min-w-0 items-start gap-3 rounded-md border p-4 shadow-sm"
                        >
                          <AlertTriangle
                            className={cn(
                              'mt-0.5 size-4 shrink-0',
                              finding.severity === 'blocking' ? 'text-danger' : 'text-warning',
                            )}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="type-body-sm text-foreground">
                              {finding.description}
                            </div>
                            <div className="type-caption mt-1">{finding.fix}</div>
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              <Badge tone="neutral" className="font-mono lowercase">
                                {finding.effort}
                              </Badge>
                              <span className="text-secondary font-sans text-xs font-medium">
                                {finding.action}
                              </span>
                            </div>
                            <EvidenceChips evidence={finding.evidence} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="border-success-border bg-success-bg text-success-text flex w-full max-w-[760px] items-center gap-2.5 rounded-md border p-3.5">
                      <Check className="text-success-text size-4 shrink-0" />
                      <span className="type-subheading text-success-text font-medium">
                        Required AI discoverability signals are present for this dimension.
                      </span>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <DataRegionEmpty
          title="Ready for signal audit"
          description="Run an audit to inspect catalog discoverability signals."
        />
      )}
    </TableSurface>
  );
}

export function UcpContractPanel({ report }: Readonly<{ report: UcpAuditReport | null }>) {
  const contract = getContract(report);
  const catalog = contract.catalog ?? {};
  const markup = contract.structured_markup ?? {};
  const discovery = contract.discovery ?? {};
  const productRecords = contract.product_records ?? [];
  const aiAssessment = contract.ai_assessment ?? {};
  const aiResults = aiAssessment.results ?? [];
  const unansweredQueries = aiResults.flatMap((result) =>
    (result.simulated_queries ?? []).filter((query) => !query.answerable),
  );
  const quality = productSampleQuality(productRecords);

  return (
    <TableSurface>
      <header className="border-divider bg-background/25 flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="type-label-mono">SIGNAL AUDIT</h2>
          <p className="type-caption mt-0.5">
            Catalog crawl, structured markup, and AI crawler discovery signals.
          </p>
        </div>
        {report ? (
          <Badge tone={productRecords.length ? 'success' : 'warning'}>
            {productRecords.length} product samples
          </Badge>
        ) : null}
      </header>

      {report ? (
        <div className="grid gap-5 p-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <ManifestFact
              label="Pages crawled"
              value={formatUnknownText(catalog.pages_crawled, '0')}
              tone={Number(catalog.pages_crawled ?? 0) > 0 ? 'success' : 'danger'}
            />
            <ManifestFact
              label="Product JSON-LD"
              value={formatUnknownText(markup.product_jsonld_count, '0')}
              tone={Number(markup.product_jsonld_count ?? 0) > 0 ? 'success' : 'danger'}
            />
            <ManifestFact
              label="Sitemap"
              value={discovery.sitemap_found ? 'found' : 'missing'}
              tone={discovery.sitemap_found ? 'success' : 'warning'}
            />
            <ManifestFact
              label="Crawl errors"
              value={formatUnknownText(catalog.crawl_errors?.length ?? 0)}
              tone={catalog.crawl_errors?.length ? 'warning' : 'success'}
            />
          </div>

          <SignalSection title="BRAND READINESS">
            <div className="grid gap-3 md:grid-cols-3">
              <SignalMetric
                label="Core fields"
                value={`${quality.coreReady}/${productRecords.length || 0}`}
                tone={
                  quality.coreReady === productRecords.length && productRecords.length
                    ? 'success'
                    : 'warning'
                }
              />
              <SignalMetric
                label="Variant clarity"
                value={`${quality.variantReady}/${productRecords.length || 0}`}
                tone={
                  quality.variantReady === productRecords.length && productRecords.length
                    ? 'success'
                    : 'warning'
                }
              />
              <SignalMetric
                label="AI unanswered queries"
                value={formatUnknownText(unansweredQueries.length, '0')}
                tone={unansweredQueries.length ? 'warning' : 'success'}
              />
            </div>
          </SignalSection>

          <SignalSection title="SAMPLED URLS">
            <SampledUrlList urls={catalog.sampled_urls ?? []} />
          </SignalSection>

          <SignalSection title="STRUCTURED MARKUP">
            <div className="grid gap-3 lg:grid-cols-[220px_220px_1fr]">
              <SignalMetric
                label="JSON-LD blocks"
                value={formatUnknownText(markup.jsonld_block_count, '0')}
                tone={Number(markup.jsonld_block_count ?? 0) > 0 ? 'success' : 'warning'}
              />
              <SignalMetric
                label="Product JSON-LD"
                value={formatUnknownText(markup.product_jsonld_count, '0')}
                tone={Number(markup.product_jsonld_count ?? 0) > 0 ? 'success' : 'danger'}
              />
              <OpenGraphSummary tags={markup.open_graph ?? {}} />
            </div>
            {markup.jsonld_parse_errors?.length ? (
              <div className="mt-3">
                <EvidenceChips
                  evidence={markup.jsonld_parse_errors.map((error) => ({ jsonld_error: error }))}
                />
              </div>
            ) : null}
          </SignalSection>

          <SignalSection title="ROBOTS DIRECTIVES">
            <RobotsSummary directives={discovery.robots_directives ?? {}} />
          </SignalSection>

          <AiAssessmentSummary assessment={aiAssessment} />

          <div>
            <h3 className="type-label-mono mb-2">PRODUCT SAMPLE MATRIX</h3>
            {productRecords.length ? (
              <div className="overflow-x-auto">
                <Table className="min-w-[760px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>URL</TableHead>
                      <TableHead>Title</TableHead>
                      <TableHead>Price</TableHead>
                      <TableHead>Brand</TableHead>
                      <TableHead>AI-ready fields</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {productRecords.map((record) => (
                      <TableRow
                        key={[
                          formatUnknownText(record.source_url, 'sample'),
                          formatUnknownText(record.title ?? record.name, 'untitled'),
                          formatUnknownText(record.price, 'unpriced'),
                        ].join(':')}
                      >
                        <TableCell className="font-mono text-xs">
                          <span title={formatUnknownText(record.source_url, '-')}>
                            {compactUrl(formatUnknownText(record.source_url, '-'))}
                          </span>
                        </TableCell>
                        <TableCell>{formatUnknownText(record.title ?? record.name, '-')}</TableCell>
                        <TableCell>{formatUnknownText(record.price, '-')}</TableCell>
                        <TableCell>{formatUnknownText(record.brand, '-')}</TableCell>
                        <TableCell>
                          <FieldCoverageChips record={record} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <DataRegionEmpty
                title="No product samples"
                description="The crawl did not extract product records."
              />
            )}
          </div>
        </div>
      ) : (
        <div className="py-8">
          <DataRegionEmpty
            title="No signal payload"
            description="Run an audit to inspect catalog discoverability signals."
          />
        </div>
      )}
    </TableSurface>
  );
}

export function UcpFixSequence({ report }: Readonly<{ report: UcpAuditReport | null }>) {
  const roadmap = useMemo(() => getRoadmap(report), [report]);
  const storageKey = report?.job_id ? `ucp-fix-sequence-${report.job_id}` : null;
  const [done, setDone] = useState<Record<string, boolean>>(() => {
    if (storageKey && typeof globalThis.window !== 'undefined') {
      try {
        const stored = globalThis.window.localStorage.getItem(storageKey);
        if (stored) return JSON.parse(stored) as Record<string, boolean>;
      } catch {
        // Ignore invalid JSON
      }
    }
    return {};
  });

  // Re-sync from localStorage when the audit report (and storageKey) changes.
  // Uses the derive-state-from-prop pattern instead of setState-in-effect so
  // we don't cascade an extra render when the storageKey hasn't changed.
  const prevStorageKeyRef = useRef(storageKey);
  if (storageKey !== prevStorageKeyRef.current) {
    prevStorageKeyRef.current = storageKey;
    if (!storageKey || typeof globalThis.window === 'undefined') {
      setDone({});
    } else {
      try {
        const stored = globalThis.window.localStorage.getItem(storageKey);
        setDone(stored ? (JSON.parse(stored) as Record<string, boolean>) : {});
      } catch {
        setDone({});
      }
    }
  }
  const doneCount = roadmap.filter((item) => done[item.id]).length;
  const progressPercent = roadmap.length ? Math.round((doneCount / roadmap.length) * 100) : 0;

  function toggle(id: string) {
    const next = { ...done, [id]: !done[id] };
    setDone(next);
    if (storageKey && globalThis.window !== undefined) {
      globalThis.window.localStorage.setItem(storageKey, JSON.stringify(next));
    }
  }

  function exportPlan() {
    const lines = roadmap.map((item, index) => {
      const checked = done[item.id] ? 'x' : ' ';
      const evidenceLines = evidenceToLines(item.evidence)
        .map((line) => `   - ${line}`)
        .join('\n');
      const evidenceBlock = evidenceLines ? `\n${evidenceLines}` : '';
      return `- [${checked}] ${index + 1}. [${item.subSkill}] ${item.action} (${item.priority}, ${item.effort})\n   Source: ${item.source}${evidenceBlock}`;
    });
    const domain = formatUnknownText(report?.report_json?.domain, 'Audit Store');
    const content = `# AI Discoverability Repair Roadmap\n\nTarget Domain: ${domain}\nOverall Score: ${report?.overall_score ?? 0}/100\n\n${lines.join('\n\n')}\n`;
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `aid-repair-roadmap-${report?.job_id ?? 'audit'}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <TableSurface>
      <header className="border-divider bg-background/25 flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="type-label-mono">REPAIR ROADMAP</h2>
          <p className="type-caption mt-0.5">Grouped by AI discoverability repair area.</p>
        </div>
        <Button
          type="button"
          variant="download"
          size="sm"
          onClick={exportPlan}
          disabled={!roadmap.length}
        >
          <Download className="size-3.5" />
          Export roadmap
        </Button>
      </header>

      {roadmap.length ? (
        <div className="divide-divider flex flex-col gap-0 divide-y">
          <div className="bg-background/10 flex flex-wrap items-center justify-between gap-4 px-4 py-3">
            <div className="flex items-center gap-2">
              <CheckSquare className="text-success size-4" />
              <span className="type-label-mono text-foreground">ROADMAP PROGRESS:</span>
              <span className="type-caption-mono bg-background border-border text-success rounded border px-1.5 py-0.5">
                {doneCount} of {roadmap.length} fixed ({progressPercent}%)
              </span>
            </div>
            <div className="bg-border h-2 w-full shrink-0 overflow-hidden rounded-full md:w-48">
              <div
                className="bg-success h-full rounded-full transition-all duration-500"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          <ol className="divide-divider divide-y">
            {roadmap.map((item, index) => {
              const isChecked = done[item.id];
              const priorityTone = roadmapPriorityTone(item.priority);
              return (
                <li
                  key={item.id}
                  className={cn(
                    'grid gap-3 px-4 py-3.5 transition-all sm:grid-cols-[auto_1fr_auto] sm:items-start',
                    isChecked ? 'bg-background/10 opacity-70' : 'hover:bg-background/20',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggle(item.id)}
                    className={cn(
                      'border-border mt-0.5 flex size-5 cursor-pointer items-center justify-center rounded-sm border transition-all',
                      isChecked
                        ? 'bg-success border-success text-white'
                        : 'bg-background hover:border-accent',
                    )}
                    aria-label="Toggle roadmap action"
                  >
                    {isChecked ? <Check className="size-3.5" /> : null}
                  </button>

                  <div className="min-w-0">
                    <div
                      className={cn(
                        'type-body-sm text-foreground flex flex-wrap items-center gap-2',
                        isChecked && 'text-muted line-through',
                      )}
                    >
                      <span className="text-secondary font-mono text-xs">{index + 1}.</span>
                      <span className="bg-background border-border text-foreground rounded border px-1.5 py-0.5 font-mono text-xs font-medium">
                        {item.subSkill}
                      </span>
                      <span>{item.action}</span>
                    </div>
                    <p className="type-caption mt-1">Source: {item.source}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge tone="neutral" className="font-mono lowercase">
                        {item.effort}
                      </Badge>
                      {item.dependsOn.length ? (
                        <span className="text-muted font-mono text-xs">
                          Depends: {item.dependsOn.join(', ')}
                        </span>
                      ) : null}
                    </div>
                    <EvidenceChips evidence={item.evidence} />
                  </div>

                  <Badge tone={priorityTone}>{item.priority}</Badge>
                </li>
              );
            })}
          </ol>
        </div>
      ) : (
        <div className="py-8">
          <DataRegionEmpty
            title="No repair items"
            description="No AI discoverability gaps were emitted for this run."
          />
        </div>
      )}
    </TableSurface>
  );
}

function ManifestFact({
  label,
  value,
  tone,
  detail,
}: Readonly<{ label: string; value: string; tone: string; detail?: string }>) {
  return (
    <div className="border-border bg-panel rounded-md border p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="type-label text-secondary">{label}</span>
        <Badge tone={badgeTone(tone)}>{value}</Badge>
      </div>
      {detail ? (
        <div className="text-foreground mt-1 font-mono text-xs break-all">{detail}</div>
      ) : null}
    </div>
  );
}

function AiAssessmentSummary({
  assessment,
}: Readonly<{ assessment: NonNullable<UcpContract['ai_assessment']> }>) {
  const results = assessment.results ?? [];
  const errorCount = results.filter((result) => result.error).length;
  const queries = results.flatMap((result) => result.simulated_queries ?? []);
  const contradictions = assessment.contradictions ?? [];

  if (!assessment.enabled && !results.length && !contradictions.length) {
    return (
      <SignalSection title="AI REASONING">
        <DataRegionEmpty
          title="AI reasoning not run"
          description="Enable AI reasoning before starting an audit to test shopper-query answerability."
        />
      </SignalSection>
    );
  }

  return (
    <SignalSection title="AI REASONING">
      <div className="grid gap-3 lg:grid-cols-[1fr_1fr]">
        <div className="grid gap-2">
          <div className="type-label text-secondary">Shopper-query simulation</div>
          {queries.length ? (
            queries.slice(0, 6).map((query) => (
              <div key={query.query} className="border-border bg-panel rounded-md border p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="type-body-sm text-foreground">{query.query}</p>
                  <Badge tone={query.answerable ? 'success' : 'warning'}>
                    {query.answerable ? 'answerable' : 'gap'}
                  </Badge>
                </div>
                {query.gap ? <p className="type-caption mt-1">{query.gap}</p> : null}
              </div>
            ))
          ) : (
            <p className="type-caption">No simulated queries returned.</p>
          )}
        </div>

        <div className="grid gap-2">
          <div className="type-label text-secondary">Cross-signal conflicts</div>
          {contradictions.length ? (
            contradictions.map((row) => (
              <div
                key={`${row.url}-${JSON.stringify(row.flags ?? [])}`}
                className="border-warning/40 bg-warning/5 rounded-md border p-3"
              >
                <div className="type-caption-mono mb-2">
                  {compactUrl(formatUnknownText(row.url, '-'))}
                </div>
                <EvidenceChips evidence={(row.flags ?? []) as Array<Record<string, unknown>>} />
              </div>
            ))
          ) : (
            <div className="border-success-border bg-success-bg rounded-md border p-3">
              <p className="type-caption text-success-text">No deterministic conflicts found.</p>
            </div>
          )}
          {errorCount ? (
            <div className="border-warning/40 bg-warning/5 rounded-md border p-3">
              <p className="type-caption">
                AI reasoning was unavailable for {errorCount} product sample
                {errorCount === 1 ? '' : 's'}.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </SignalSection>
  );
}

function SignalSection({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <section className="border-border bg-background/20 rounded-md border p-3.5">
      <h3 className="type-label-mono mb-3">{title}</h3>
      {children}
    </section>
  );
}

function SignalMetric({
  label,
  value,
  tone,
}: Readonly<{ label: string; value: string; tone: string }>) {
  return (
    <div className="border-border bg-panel rounded-md border p-3">
      <div className="type-label text-secondary">{label}</div>
      <div
        className={cn(
          'mt-2 font-mono text-2xl font-semibold tabular-nums',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
        )}
      >
        {value}
      </div>
    </div>
  );
}

function SampledUrlList({ urls }: Readonly<{ urls: string[] }>) {
  if (!urls.length) {
    return (
      <DataRegionEmpty
        title="No sampled URLs"
        description="The crawl did not return URL samples."
      />
    );
  }
  return (
    <ol className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {urls.map((url, index) => (
        <li
          key={url}
          className="border-border bg-panel flex min-w-0 items-center gap-2 rounded-md border px-3 py-2.5"
        >
          <span className="bg-background border-border text-muted text-2xs grid size-6 shrink-0 place-items-center rounded border font-mono">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-foreground truncate font-mono text-xs" title={url}>
              {compactUrl(url)}
            </div>
            <div className="type-caption mt-0.5">{urlRole(url, index)}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

function OpenGraphSummary({ tags }: Readonly<{ tags: Record<string, string> }>) {
  const entries = Object.entries(tags)
    .filter(([, value]) => formatUnknownText(value).trim())
    .slice(0, 6);
  if (!entries.length) {
    return (
      <div className="border-border bg-panel rounded-md border p-3">
        <div className="type-label text-secondary">Open Graph</div>
        <div className="type-caption mt-2">No product tags found</div>
      </div>
    );
  }
  return (
    <div className="border-border bg-panel min-w-0 rounded-md border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="type-label text-secondary">Open Graph</span>
        <Badge tone="success">{entries.length} tags</Badge>
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <div key={key} className="min-w-0">
            <div className="type-caption-mono">{key}</div>
            <div className="type-caption text-foreground truncate" title={formatUnknownText(value)}>
              {shortText(formatUnknownText(value), 72)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RobotsSummary({ directives }: Readonly<{ directives: Record<string, string[]> }>) {
  const rows = ['gptbot', 'perplexitybot'].map((agent) => {
    const disallows = directives[agent] ?? directives[agent.toLowerCase()] ?? [];
    const blocked = disallows.some((rule) => String(rule).trim() === '/');
    return { agent, blocked, ruleCount: disallows.length };
  });
  const totalRules = Object.values(directives).reduce((sum, rules) => sum + rules.length, 0);
  return (
    <div className="grid gap-3 md:grid-cols-[1fr_1fr_180px]">
      {rows.map((row) => (
        <div key={row.agent} className="border-border bg-panel rounded-md border p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-foreground font-mono text-xs">{row.agent}</span>
            <Badge tone={row.blocked ? 'danger' : 'success'}>
              {row.blocked ? 'blocked' : 'allowed'}
            </Badge>
          </div>
          <div className="type-caption">{row.ruleCount} disallow rules</div>
        </div>
      ))}
      <div className="border-border bg-panel rounded-md border p-3">
        <div className="type-label text-secondary">Total rules</div>
        <div className="text-foreground mt-2 font-mono text-2xl font-semibold tabular-nums">
          {totalRules}
        </div>
      </div>
    </div>
  );
}

function FieldCoverageChips({ record }: Readonly<{ record: Record<string, unknown> }>) {
  const checks = [
    ['title', Boolean(formatUnknownText(record.title ?? record.name))],
    ['price', Boolean(formatUnknownText(record.price))],
    ['description', formatUnknownText(record.description).length >= 100],
    ['image', Boolean(formatUnknownText(record.image_url ?? record.image ?? record.images))],
    ['variant', Boolean(formatUnknownText(record.variants ?? record.size ?? record.color))],
  ];
  return (
    <div className="flex max-w-[280px] flex-wrap gap-1">
      {checks.map(([label, ok]) => (
        <Badge
          key={String(label)}
          tone={ok ? 'success' : 'warning'}
          className="font-mono lowercase"
        >
          {String(label)}
        </Badge>
      ))}
    </div>
  );
}

function EvidenceChips({ evidence }: Readonly<{ evidence: Array<Record<string, unknown>> }>) {
  const lines = evidenceToLines(evidence);
  if (!lines.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {lines.map((line) => (
        <code
          key={line}
          className="text-foreground bg-background-alt/80 border-border/80 rounded border px-1.5 py-0.5 font-mono text-xs"
        >
          {line}
        </code>
      ))}
    </div>
  );
}

function evidenceToLines(evidence: Array<Record<string, unknown>> = []): string[] {
  const lines = evidence.flatMap((entry) =>
    Object.entries(entry).flatMap(([key, value]) => {
      if (Array.isArray(value)) {
        return value.flatMap((item) => {
          const line = `${key}: ${formatEvidenceValue(item)}`;
          return line.trim().length > 0 ? [line] : [];
        });
      }
      const line =
        value && typeof value === 'object'
          ? `${key}: ${JSON.stringify(value)}`
          : `${key}: ${formatEvidenceValue(value)}`;
      return line.trim().length > 0 ? [line] : [];
    }),
  );
  return lines.slice(0, 12);
}

function formatEvidenceValue(value: unknown): string {
  return formatUnknownText(value, '-');
}

function formatUnknownText(value: unknown, fallback = ''): string {
  if (value == null || value === '') return fallback;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  if (Array.isArray(value)) {
    const items = value.flatMap((item) => {
      const text = formatUnknownText(item);
      return text ? [text] : [];
    });
    return items.length ? items.join(', ') : fallback;
  }
  try {
    return JSON.stringify(value) ?? fallback;
  } catch {
    return fallback;
  }
}

function productSampleQuality(records: Array<Record<string, unknown>>) {
  return records.reduce<{ coreReady: number; variantReady: number }>(
    (summary, record) => {
      const hasTitle = Boolean(formatUnknownText(record.title ?? record.name));
      const hasPrice = Boolean(formatUnknownText(record.price));
      const hasDescription = formatUnknownText(record.description).length >= 100;
      const hasImage = Boolean(
        formatUnknownText(record.image_url ?? record.image ?? record.images),
      );
      const hasVariant = Boolean(formatUnknownText(record.variants ?? record.size ?? record.color));
      return {
        coreReady: summary.coreReady + (hasTitle && hasPrice && hasDescription && hasImage ? 1 : 0),
        variantReady: summary.variantReady + (hasVariant ? 1 : 0),
      };
    },
    { coreReady: 0, variantReady: 0 },
  );
}

function compactUrl(value: string): string {
  try {
    const parsed = new URL(value);
    const path = parsed.pathname === '/' ? '/' : parsed.pathname.replace(/\/$/, '');
    return `${parsed.hostname}${path}`;
  } catch {
    return shortText(value, 96);
  }
}

function urlRole(url: string, index: number): string {
  if (index === 0) return 'entry page';
  if (/\/(?:products?|p)\//i.test(url)) return 'product page';
  return 'sample page';
}

function shortText(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1))}...`;
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
    <Card
      className={cn(
        'hover:border-accent/60 bg-panel border-border relative flex min-h-[160px] flex-col justify-between rounded-lg border p-5 duration-300 ease-out hover:scale-[1.02] hover:shadow-md',
        blocked && 'pointer-events-none opacity-35 select-none',
      )}
    >
      {blocked ? (
        <div className="bg-background/10 absolute inset-0 z-10 flex items-center justify-center rounded-lg backdrop-blur-[0.5px]">
          <span className="type-caption-mono text-danger border-danger/45 bg-background/90 rotate-12 rounded border px-2 py-0.5 shadow">
            BLOCKED
          </span>
        </div>
      ) : null}
      <div className="flex items-start justify-between gap-3">
        <ScoreRing score={dimension.score} size={70} stroke={8} compact />
        {dimension.findings.length ? (
          <Badge tone="danger" className="type-caption-mono">
            {dimension.findings.length} gaps
          </Badge>
        ) : (
          <Badge tone="success" className="type-caption-mono">
            READY
          </Badge>
        )}
      </div>
      <div className="mt-3.5">
        <h4 className="type-subheading text-foreground">{meta.label}</h4>
        <p className="type-caption mt-1.5 mb-0">{meta.subtitle}</p>
      </div>
    </Card>
  );
}

function SummaryRow({
  label,
  value,
  tone,
}: Readonly<{ label: string; value: string | number; tone: string }>) {
  const badgeToneVal =
    tone === 'success' ||
    tone === 'warning' ||
    tone === 'danger' ||
    tone === 'neutral' ||
    tone === 'accent' ||
    tone === 'info'
      ? tone
      : 'neutral';

  return (
    <div className="border-border/40 flex items-center justify-between border-b pb-1.5">
      <span className="type-label">{label}</span>
      <Badge tone={badgeToneVal} className="font-mono lowercase">
        {value}
      </Badge>
    </div>
  );
}

function ScoreRing({
  score,
  size,
  stroke,
  compact = false,
}: Readonly<{ score: number; size: number; stroke: number; compact?: boolean }>) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.max(0, Math.min(100, score)) / 100) * circumference;
  return (
    <div
      className="relative grid shrink-0 place-items-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id="score-ring-success" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--success)" />
            <stop offset="100%" stopColor="color-mix(in srgb, var(--success) 60%, black)" />
          </linearGradient>
          <linearGradient id="score-ring-warning" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--warning)" />
            <stop offset="100%" stopColor="color-mix(in srgb, var(--warning) 60%, black)" />
          </linearGradient>
          <linearGradient id="score-ring-danger" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--danger)" />
            <stop offset="100%" stopColor="color-mix(in srgb, var(--danger) 60%, black)" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="stroke-border-subtle/50"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={
            score >= 80
              ? 'url(#score-ring-success)'
              : score >= 50
                ? 'url(#score-ring-warning)'
                : 'url(#score-ring-danger)'
          }
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 800ms ease-out' }}
        />
      </svg>
      <div className="absolute text-center select-none">
        <div
          className={cn(
            'text-foreground font-semibold tabular-nums',
            compact ? 'type-display-sm' : 'type-display',
          )}
        >
          {score}
        </div>
        {!compact && <div className="type-caption-mono mt-0.5 leading-none">/100</div>}
      </div>
    </div>
  );
}

function LoadingScoreRing({ size }: Readonly<{ size: number }>) {
  return (
    <div
      className="border-border bg-background-alt grid animate-pulse place-items-center rounded-full border"
      style={{ width: size, height: size }}
    >
      <div className="bg-border h-10 w-16 rounded" />
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
  const code = formatUnknownText(finding.code, 'unknown_finding');
  const dimension = formatUnknownText(finding.dimension_id ?? finding.dimension);
  const copy = FINDING_COPY[code] ?? {
    description: formatUnknownText(finding.message, code),
    fix: 'Inspect the exported signal payload and repair the missing catalog signal.',
    effort: 'review',
    action: `Resolve ${code}`,
    impact: 'medium' as const,
  };
  return {
    id: `${dimension}-${code}-${index}`,
    code,
    dimension,
    severity: formatUnknownText(finding.severity, 'info'),
    description: formatUnknownText(finding.message, copy.description),
    fix: copy.fix,
    effort: copy.effort,
    action: copy.action,
    impact: copy.impact,
    evidence: Array.isArray(finding.evidence)
      ? (finding.evidence as Array<Record<string, unknown>>)
      : [],
  };
}

function getContract(report: UcpAuditReport | null): UcpContract {
  const raw = report?.report_json?.ucp_contract;
  return raw && typeof raw === 'object' ? raw : {};
}

function getRoadmap(report: UcpAuditReport | null) {
  const raw = report?.report_json?.repair_roadmap;
  if (Array.isArray(raw) && raw.length) {
    return raw.map((item, index) => {
      const roadmap = item;
      const subSkill = formatUnknownText(roadmap.sub_skill, 'aid');
      return {
        id: `${subSkill}-${index}`,
        subSkill,
        priority: formatUnknownText(roadmap.priority, 'medium'),
        action: formatUnknownText(roadmap.action, 'Repair AI discoverability signal'),
        source: formatUnknownText(roadmap.source, 'AI Discoverability Score guidance'),
        evidence: Array.isArray(roadmap.evidence)
          ? (roadmap.evidence as Array<Record<string, unknown>>)
          : [],
        effort: formatUnknownText(roadmap.effort, 'review'),
        dependsOn: Array.isArray(roadmap.depends_on)
          ? roadmap.depends_on.map(formatUnknownText)
          : [],
      };
    });
  }
  return (report?.findings ?? []).map((finding, index) => {
    const normalized = normalizeFinding(finding, index);
    return {
      id: normalized.id,
      subSkill: normalized.dimension,
      priority: normalized.impact,
      action: normalized.action,
      source: 'AI Discoverability Score guidance',
      evidence: normalized.evidence,
      effort: normalized.effort,
      dependsOn: [],
    };
  });
}

function scoreTone(score: number) {
  if (score >= 80) return 'success';
  if (score >= 50) return 'warning';
  return 'danger';
}

function roadmapPriorityTone(priority: string) {
  if (priority === 'critical') return 'danger';
  if (priority === 'high') return 'warning';
  return 'neutral';
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
