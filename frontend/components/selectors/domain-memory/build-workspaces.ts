import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfileRecord,
  SelectorDomainSummary,
} from '../../../lib/api/types';
import { getNormalizedDomain, isSpecialUseDomain } from '../../../lib/format/domain';
import type { DomainWorkspace, LocalRecord, SurfaceWorkspace } from './types';
import {
  feedbackSearchText,
  isInternalDomainMemoryArtifact,
  profileSearchText,
  selectorValue,
} from './utils';

type BuildDomainWorkspacesInput = {
  completedRuns: CrawlRun[];
  cookies: DomainCookieMemoryRecord[];
  feedback: DomainFieldFeedbackRecord[];
  profiles: DomainRunProfileRecord[];
  records: LocalRecord[];
  selectorSummaries: SelectorDomainSummary[];
  searchQuery: string;
  surfaceFilter: string;
};

export function buildDomainWorkspaces({
  completedRuns,
  cookies,
  feedback,
  profiles,
  records,
  selectorSummaries,
  searchQuery,
  surfaceFilter,
}: BuildDomainWorkspacesInput): DomainWorkspace[] {
  const query = searchQuery.trim().toLowerCase();
  const byDomain = new Map<string, Map<string, SurfaceWorkspace>>();
  const cookiesByDomain = new Map(cookies.map((row) => [row.domain, row] as const));
  const runsByDomain = new Map<string, Map<string, CrawlRun[]>>();

  function ensureSurfaceWorkspace(domain: string, surface: string): SurfaceWorkspace {
    const domainEntry = byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>();
    if (!byDomain.has(domain)) byDomain.set(domain, domainEntry);
    const existing = domainEntry.get(surface);
    if (existing) return existing;
    const created: SurfaceWorkspace = {
      surface,
      selectorCount: 0,
      selectors: [],
      profile: null,
      learning: [],
      completedRuns: [],
    };
    domainEntry.set(surface, created);
    return created;
  }

  function ensureDomainRuns(domain: string, surface: string) {
    const domainEntry = runsByDomain.get(domain) ?? new Map<string, CrawlRun[]>();
    if (!runsByDomain.has(domain)) runsByDomain.set(domain, domainEntry);
    const existing = domainEntry.get(surface);
    if (existing) return existing;
    const created: CrawlRun[] = [];
    domainEntry.set(surface, created);
    return created;
  }

  for (const summary of selectorSummaries) {
    if (surfaceFilter !== 'all' && summary.surface !== surfaceFilter) continue;
    const searchable = [summary.domain, summary.surface].join(' ').toLowerCase();
    if (query && !searchable.includes(query) && !summary.domain.toLowerCase().includes(query)) {
      continue;
    }
    ensureSurfaceWorkspace(summary.domain, summary.surface).selectorCount = summary.selector_count;
  }

  for (const record of records) {
    if (surfaceFilter !== 'all' && record.surface !== surfaceFilter) continue;
    const searchable = [
      record.domain,
      record.surface,
      record.field_name,
      record.source,
      selectorValue(record),
    ]
      .join(' ')
      .toLowerCase();
    if (query && !searchable.includes(query) && !record.domain.toLowerCase().includes(query)) {
      continue;
    }
    const workspace = ensureSurfaceWorkspace(record.domain, record.surface);
    workspace.selectors.push(record);
    workspace.selectorCount = Math.max(workspace.selectorCount, workspace.selectors.length);
  }

  for (const profile of profiles) {
    if (surfaceFilter !== 'all' && profile.surface !== surfaceFilter) continue;
    if (
      query &&
      !profileSearchText(profile).includes(query) &&
      !profile.domain.toLowerCase().includes(query)
    ) {
      continue;
    }
    ensureSurfaceWorkspace(profile.domain, profile.surface).profile = profile;
  }

  for (const row of feedback) {
    if (surfaceFilter !== 'all' && row.surface !== surfaceFilter) continue;
    if (
      query &&
      !feedbackSearchText(row).includes(query) &&
      !row.domain.toLowerCase().includes(query)
    ) {
      continue;
    }
    ensureSurfaceWorkspace(row.domain, row.surface).learning.push(row);
  }

  for (const run of completedRuns) {
    const domain = String(run.result_summary?.domain || '').trim() || getNormalizedDomain(run.url);
    if (!domain || isSpecialUseDomain(domain)) continue;
    if (surfaceFilter !== 'all' && run.surface !== surfaceFilter) continue;
    const searchable = [domain, run.surface, run.url, run.status].join(' ').toLowerCase();
    if (query && !searchable.includes(query) && !domain.toLowerCase().includes(query)) continue;
    ensureDomainRuns(domain, run.surface).push(run);
    ensureSurfaceWorkspace(domain, run.surface).completedRuns.push(run);
  }

  const visibleDomains = new Set<string>([
    ...byDomain.keys(),
    ...runsByDomain.keys(),
    ...cookies
      .filter(
        (row) => surfaceFilter === 'all' && (!query || row.domain.toLowerCase().includes(query)),
      )
      .map((row) => row.domain),
  ]);

  const workspaces: DomainWorkspace[] = [];
  for (const domain of visibleDomains) {
    const normalizedDomain = String(domain || '').trim();
    if (!normalizedDomain || isSpecialUseDomain(normalizedDomain)) continue;
    const surfaces = Array.from(
      (byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>()).values(),
    ).sort((left, right) => left.surface.localeCompare(right.surface));
    const completedRunCount = surfaces.reduce(
      (count, surface) => count + surface.completedRuns.length,
      0,
    );
    const latestCompletedAt = latestCompletedAtFor(surfaces);
    const cookieMemory = cookiesByDomain.get(domain) ?? null;
    const learning = surfaces.flatMap((surface) => surface.learning);
    if (
      isInternalDomainMemoryArtifact(
        normalizedDomain,
        surfaces.length,
        Boolean(cookieMemory),
        learning.length,
        completedRunCount,
      )
    ) {
      continue;
    }
    if (!surfaces.length && !cookieMemory) continue;
    workspaces.push({
      domain,
      surfaces,
      cookieMemory,
      learning,
      completedRunCount,
      latestCompletedAt,
    });
  }

  return workspaces.sort(compareDomainWorkspaces);
}

function latestCompletedAtFor(surfaces: SurfaceWorkspace[]) {
  return (
    surfaces
      .flatMap((surface) => surface.completedRuns)
      .map((run) => run.completed_at ?? run.updated_at ?? run.created_at)
      .filter(Boolean)
      .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null
  );
}

function compareDomainWorkspaces(left: DomainWorkspace, right: DomainWorkspace) {
  const completedDelta = right.completedRunCount - left.completedRunCount;
  if (completedDelta !== 0) return completedDelta;
  const leftTime = left.latestCompletedAt ? new Date(left.latestCompletedAt).getTime() : 0;
  const rightTime = right.latestCompletedAt ? new Date(right.latestCompletedAt).getTime() : 0;
  if (rightTime !== leftTime) return rightTime - leftTime;
  const leftMemoryScore = memoryScore(left);
  const rightMemoryScore = memoryScore(right);
  if (rightMemoryScore !== leftMemoryScore) return rightMemoryScore - leftMemoryScore;
  return left.domain.localeCompare(right.domain);
}

function memoryScore(workspace: DomainWorkspace) {
  return (
    workspace.surfaces.reduce((count, surface) => count + surface.selectorCount, 0) +
    workspace.surfaces.filter((surface) => surface.profile).length +
    workspace.learning.length +
    (workspace.cookieMemory ? 1 : 0)
  );
}
