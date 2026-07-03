import type {
  CrawlRun,
  DomainCookieMemoryRecord,
  DomainFieldFeedbackRecord,
  DomainRunProfileRecord,
  KnowledgeSiteRecord,
} from '../../../lib/api/types';
import { getNormalizedDomain, isSpecialUseDomain } from '../../../lib/format/domain';
import type { DomainWorkspace, SurfaceWorkspace } from './types';
import { feedbackSearchText, isInternalDomainMemoryArtifact, profileSearchText } from './utils';

type BuildDomainWorkspacesInput = {
  completedRuns: CrawlRun[];
  cookies: DomainCookieMemoryRecord[];
  feedback: DomainFieldFeedbackRecord[];
  knowledgeSites: KnowledgeSiteRecord[];
  profiles: DomainRunProfileRecord[];
  searchQuery: string;
  surfaceFilter: string;
};

type WorkspaceIndex = Map<string, Map<string, SurfaceWorkspace>>;

function ensureSurfaceWorkspace(byDomain: WorkspaceIndex, domain: string, surface: string) {
  const domainEntry = byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>();
  if (!byDomain.has(domain)) byDomain.set(domain, domainEntry);
  const existing = domainEntry.get(surface);
  if (existing) return existing;
  const created: SurfaceWorkspace = { surface, profile: null, learning: [], completedRuns: [] };
  domainEntry.set(surface, created);
  return created;
}

function matchesWorkspaceFilter(
  surfaceFilter: string,
  query: string,
  surface: string,
  domain: string,
  searchable: string,
) {
  return (
    (surfaceFilter === 'all' || surface === surfaceFilter) &&
    (!query || searchable.includes(query) || domain.toLowerCase().includes(query))
  );
}

function indexProfiles(
  byDomain: WorkspaceIndex,
  profiles: DomainRunProfileRecord[],
  surfaceFilter: string,
  query: string,
) {
  for (const profile of profiles) {
    if (
      !matchesWorkspaceFilter(
        surfaceFilter,
        query,
        profile.surface,
        profile.domain,
        profileSearchText(profile),
      )
    )
      continue;
    ensureSurfaceWorkspace(byDomain, profile.domain, profile.surface).profile = profile;
  }
}

function indexFeedback(
  byDomain: WorkspaceIndex,
  feedback: DomainFieldFeedbackRecord[],
  surfaceFilter: string,
  query: string,
) {
  for (const row of feedback) {
    if (
      !matchesWorkspaceFilter(
        surfaceFilter,
        query,
        row.surface,
        row.domain,
        feedbackSearchText(row),
      )
    )
      continue;
    ensureSurfaceWorkspace(byDomain, row.domain, row.surface).learning.push(row);
  }
}

function indexCompletedRuns(
  byDomain: WorkspaceIndex,
  completedRuns: CrawlRun[],
  surfaceFilter: string,
  query: string,
) {
  for (const run of completedRuns) {
    const domain = String(run.result_summary?.domain || '').trim() || getNormalizedDomain(run.url);
    const searchable = [domain, run.surface, run.url, run.status].join(' ').toLowerCase();
    if (!domain || isSpecialUseDomain(domain)) continue;
    if (!matchesWorkspaceFilter(surfaceFilter, query, run.surface, domain, searchable)) continue;
    ensureSurfaceWorkspace(byDomain, domain, run.surface).completedRuns.push(run);
  }
}

function extraVisibleDomains(
  rows: ReadonlyArray<{ domain: string }>,
  surfaceFilter: string,
  query: string,
) {
  if (surfaceFilter !== 'all') return [];
  return rows.flatMap((row) =>
    !query || row.domain.toLowerCase().includes(query) ? [row.domain] : [],
  );
}

function createDomainWorkspace(
  domain: string,
  byDomain: WorkspaceIndex,
  cookiesByDomain: Map<string, DomainCookieMemoryRecord>,
  knowledgeSitesByDomain: Map<string, KnowledgeSiteRecord>,
): DomainWorkspace | null {
  const normalizedDomain = domain.trim();
  if (!normalizedDomain || isSpecialUseDomain(normalizedDomain)) return null;
  const surfaces = Array.from((byDomain.get(domain) ?? new Map()).values()).sort((left, right) =>
    left.surface.localeCompare(right.surface),
  );
  const completedRunCount = surfaces.reduce(
    (count, surface) => count + surface.completedRuns.length,
    0,
  );
  const cookieMemory = cookiesByDomain.get(domain) ?? null;
  const knowledgeSite = knowledgeSitesByDomain.get(domain) ?? null;
  const learning = surfaces.flatMap((surface) => surface.learning);
  if (
    isInternalDomainMemoryArtifact(
      normalizedDomain,
      surfaces.length,
      Boolean(cookieMemory),
      learning.length,
      completedRunCount,
    )
  )
    return null;
  if (!surfaces.length && !cookieMemory && !knowledgeSite) return null;
  return {
    domain,
    surfaces,
    cookieMemory,
    knowledgeSite,
    learning,
    completedRunCount,
    latestCompletedAt: latestCompletedAtFor(surfaces),
  };
}

export function buildDomainWorkspaces({
  completedRuns,
  cookies,
  feedback,
  knowledgeSites,
  profiles,
  searchQuery,
  surfaceFilter,
}: BuildDomainWorkspacesInput): DomainWorkspace[] {
  const query = searchQuery.trim().toLowerCase();
  const byDomain = new Map<string, Map<string, SurfaceWorkspace>>();
  const cookiesByDomain = new Map(cookies.map((row) => [row.domain, row] as const));
  const knowledgeSitesByDomain = new Map(knowledgeSites.map((row) => [row.domain, row] as const));
  indexProfiles(byDomain, profiles, surfaceFilter, query);
  indexFeedback(byDomain, feedback, surfaceFilter, query);
  indexCompletedRuns(byDomain, completedRuns, surfaceFilter, query);

  const visibleDomains = new Set<string>([
    ...byDomain.keys(),
    ...extraVisibleDomains(knowledgeSites, surfaceFilter, query),
    ...extraVisibleDomains(cookies, surfaceFilter, query),
  ]);

  return Array.from(visibleDomains)
    .map((domain) =>
      createDomainWorkspace(domain, byDomain, cookiesByDomain, knowledgeSitesByDomain),
    )
    .filter((workspace): workspace is DomainWorkspace => workspace !== null)
    .sort(compareDomainWorkspaces);
}

function latestCompletedAtFor(surfaces: SurfaceWorkspace[]) {
  let latest: string | null = null;
  let latestTime = -Infinity;
  for (const surface of surfaces) {
    for (const run of surface.completedRuns) {
      const value = run.completed_at ?? run.updated_at ?? run.created_at;
      if (!value) continue;
      const time = new Date(value).getTime();
      if (time > latestTime) {
        latestTime = time;
        latest = value;
      }
    }
  }
  return latest;
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
    workspace.surfaces.filter((surface) => surface.profile).length +
    workspace.learning.length +
    (workspace.cookieMemory ? 1 : 0) +
    (workspace.knowledgeSite ? 1 : 0)
  );
}
