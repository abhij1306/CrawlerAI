import { Braces } from 'lucide-react';

import type { ExtractionMemoryResponse } from '../../../lib/api/types';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  SurfaceSection,
} from '../../ui/patterns';
import { Badge } from '../../ui/primitives';
import { ExtractionMemoryRefreshButton, useExtractionMemory } from './use-extraction-memory';
import { surfaceLabel } from './utils';

export function SelectorsTab({ domain }: { domain: string }) {
  const { error, query } = useExtractionMemory(domain, 'Unable to load saved selectors.');
  const rows = selectorRows(query.data);

  return (
    <SurfaceSection
      title="Saved selectors"
      description="Active deterministic field rules loaded from relational extraction memory."
      icon={Braces}
      action={
        <ExtractionMemoryRefreshButton
          isFetching={query.isFetching}
          onRefresh={() => void query.refetch()}
        />
      }
      bodyClassName="p-0"
    >
      {error ? <DataRegionError message={error} /> : null}
      {query.isLoading ? (
        <DataRegionLoading count={4} />
      ) : !rows.length ? (
        <DataRegionEmpty
          title="No saved selectors"
          description="Selectors appear after a grounded correction passes replay and is activated."
        />
      ) : (
        <SelectorGroups rows={rows} />
      )}
    </SurfaceSection>
  );
}

type ScopedSelector =
  ExtractionMemoryResponse['templates'][number]['recipes'][number]['rules'][number] & {
    key: string;
    routePattern: string;
    surface: string;
  };

function selectorRows(data: ExtractionMemoryResponse | undefined): ScopedSelector[] {
  return (data?.templates ?? []).flatMap((template) =>
    template.recipes.flatMap((recipe) =>
      recipe.rules.map((rule) => ({
        ...rule,
        key: `${template.id}-${recipe.id}-${rule.id}-${rule.field_name}`,
        routePattern: template.route_pattern || template.fingerprint,
        surface: template.surface,
      })),
    ),
  );
}

function SelectorGroups({ rows }: { rows: ScopedSelector[] }) {
  const groups = new Map<string, ScopedSelector[]>();
  for (const row of rows) {
    const group = groups.get(row.surface) ?? [];
    group.push(row);
    groups.set(row.surface, group);
  }
  return (
    <div className="divide-y divide-border">
      {Array.from(groups.entries()).map(([surface, selectors]) => (
        <section key={surface}>
          <header className="flex items-center justify-between gap-3 bg-background-alt px-5 py-3">
            <span className="text-xs font-semibold text-foreground">{surfaceLabel(surface)}</span>
            <Badge tone="neutral">{selectors.length} rules</Badge>
          </header>
          <div className="divide-y divide-border">
            {selectors.map((selector) => (
              <div
                key={selector.key}
                className="grid gap-2 px-5 py-4 lg:grid-cols-[minmax(140px,0.35fr)_minmax(0,1fr)_auto] lg:items-center"
              >
                <div>
                  <div className="text-sm font-semibold text-foreground">{selector.field_name}</div>
                  <div className="mt-1 truncate font-mono text-xs text-muted">
                    {selector.routePattern}
                  </div>
                </div>
                <code className="min-w-0 text-xs break-all text-secondary">
                  {selector.css_selector || 'No CSS selector'}
                </code>
                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  <Badge tone={selector.is_active ? 'success' : 'neutral'}>
                    {selector.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                  <span className="text-xs text-muted">{selector.source}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
