import { Badge } from '../../ui/primitives';
import { NavList, SurfacePanel } from '../../ui/patterns';
import type { DomainWorkspace } from './types';
import { getProfileCount, getTotalSelectorCount } from './utils';

type DomainSidebarProps = {
  groupedWorkspaces: DomainWorkspace[];
  resolvedSelectedDomain: string;
  setSelectedDomain: (domain: string) => void;
};

export function DomainSidebar({
  groupedWorkspaces,
  resolvedSelectedDomain,
  setSelectedDomain,
}: DomainSidebarProps) {
  return (
    <SurfacePanel className="flex max-h-[calc(100vh-180px)] flex-col space-y-3 p-3">
      <div className="flex shrink-0 items-center justify-between px-1">
        <h3 className="type-label">Domains</h3>
        <span className="text-muted text-xs">{groupedWorkspaces.length}</span>
      </div>
      <div className="-mr-1 min-h-0 overflow-y-auto pr-1">
        <NavList
          items={groupedWorkspaces}
          selectedKey={resolvedSelectedDomain}
          onSelect={setSelectedDomain}
          getKey={(ws) => ws.domain}
          renderLabel={(ws) => ws.domain}
          renderMeta={(ws) => {
            const selectorCount = getTotalSelectorCount(ws.surfaces);
            const profileCount = getProfileCount(ws.surfaces);
            const meta = [
              selectorCount ? `${selectorCount} selectors` : null,
              profileCount ? `${profileCount} profiles` : null,
              ws.learning.length ? `${ws.learning.length} learned` : null,
              ws.completedRunCount ? `${ws.completedRunCount} runs` : null,
            ]
              .filter(Boolean)
              .join(' · ');
            return meta ? <span className="text-muted text-xs">{meta}</span> : null;
          }}
          renderBadge={(ws) =>
            ws.cookieMemory ? <Badge tone="accent">{ws.cookieMemory.cookie_count}</Badge> : null
          }
        />
      </div>
    </SurfacePanel>
  );
}
