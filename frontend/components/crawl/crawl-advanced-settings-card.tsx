import { Info, SlidersHorizontal } from 'lucide-react';

import type { DomainRunProfile } from '../../lib/api/types';
import { Card, Tooltip } from '../ui/primitives';
import { CrawlAdvancedDiagnostics } from './crawl-advanced-diagnostics';
import { CrawlAdvancedExecution } from './crawl-advanced-execution';
import { CrawlAdvancedLimits } from './crawl-advanced-limits';

type ProfileUpdater = (current: DomainRunProfile) => DomainRunProfile;

type Props = {
  runProfile: DomainRunProfile;
  respectRobotsTxt: boolean;
  maxRecords: string;
  onProfileChange: (updater: ProfileUpdater) => void;
  onRespectRobotsTxtChange: (value: boolean) => void;
  onMaxRecordsChange: (value: string) => void;
};

export function CrawlAdvancedSettingsCard({
  runProfile,
  respectRobotsTxt,
  maxRecords,
  onProfileChange,
  onRespectRobotsTxtChange,
  onMaxRecordsChange,
}: Readonly<Props>) {
  return (
    <Card className="section-card overflow-visible p-0 xl:col-span-2">
      <header className="flex h-[38px] items-center justify-between border-b border-border bg-background px-5">
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          <SlidersHorizontal className="size-3.5" /> Advanced Settings
        </span>
        <Tooltip content="Fine-tune fetch, limits, locality, and diagnostics for this exploratory run.">
          <Info className="text-subtle size-3.5 cursor-help transition-colors hover:text-secondary" />
        </Tooltip>
      </header>
      <div className="grid gap-0 p-6 xl:grid-cols-3 xl:divide-x xl:divide-[var(--border)]">
        <CrawlAdvancedExecution
          runProfile={runProfile}
          respectRobotsTxt={respectRobotsTxt}
          onProfileChange={onProfileChange}
          onRespectRobotsTxtChange={onRespectRobotsTxtChange}
        />
        <CrawlAdvancedLimits
          runProfile={runProfile}
          maxRecords={maxRecords}
          onProfileChange={onProfileChange}
          onMaxRecordsChange={onMaxRecordsChange}
        />
        <CrawlAdvancedDiagnostics runProfile={runProfile} onProfileChange={onProfileChange} />
      </div>
    </Card>
  );
}
