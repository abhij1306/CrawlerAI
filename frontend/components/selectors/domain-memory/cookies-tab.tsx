import { DataRegionEmpty, DetailRow, KVTile, SurfaceSection } from '../../ui/patterns';
import type { DomainWorkspace } from './types';
import { formatTimestamp } from './utils';

type CookiesTabProps = { selectedWorkspace: DomainWorkspace };

export function CookiesTab({ selectedWorkspace }: CookiesTabProps) {
  return (
    <SurfaceSection
      title="Saved Domain Cookies"
      description="Cookie memory is stored at the domain level so acquisition can reuse known session context."
      bodyClassName="space-y-3"
    >
      {selectedWorkspace.cookieMemory ? (
        <DetailRow>
          <div className="grid gap-3 sm:grid-cols-2">
            <KVTile label="Cookies" value={selectedWorkspace.cookieMemory.cookie_count} />
            <KVTile label="Origins" value={selectedWorkspace.cookieMemory.origin_count} />
          </div>
          <div className="text-muted mt-3 text-xs">
            Updated {formatTimestamp(selectedWorkspace.cookieMemory.updated_at)}
          </div>
        </DetailRow>
      ) : (
        <DataRegionEmpty
          title="No cookie memory saved"
          description="A successful authenticated or protected acquisition run will populate cookie memory here."
        />
      )}
    </SurfaceSection>
  );
}
