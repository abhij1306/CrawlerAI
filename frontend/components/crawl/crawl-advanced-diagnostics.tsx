import { Info } from 'lucide-react';

import type { DomainRunProfile } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { Dropdown, Tooltip } from '../ui/primitives';
import { SettingSection } from './form-fields';
import {
  applyDiagnosticsPreset,
  CAPTURE_NETWORK_OPTIONS,
  diagnosticsPresetForProfile,
  type CaptureNetworkMode,
  type DiagnosticsPreset,
} from './crawl-config-logic';
import {
  ADVANCED_COLUMN_CLASS,
  ADVANCED_CONTROL_ROW_CLASS,
  ADVANCED_SECTION_TITLE_CLASS,
  ADVANCED_SUBSECTION_CLASS,
} from './crawl-config-state';

type ProfileUpdater = (current: DomainRunProfile) => DomainRunProfile;

type CrawlAdvancedDiagnosticsProps = {
  runProfile: DomainRunProfile;
  onProfileChange: (updater: ProfileUpdater) => void;
};

export function CrawlAdvancedDiagnostics({
  runProfile,
  onProfileChange,
}: Readonly<CrawlAdvancedDiagnosticsProps>) {
  const diagnosticsPreset = diagnosticsPresetForProfile(runProfile);

  return (
    <section className={cn(ADVANCED_COLUMN_CLASS, 'xl:pl-6')}>
      <div className={ADVANCED_SECTION_TITLE_CLASS}>
        <h3>Output &amp; Diagnostics</h3>
        <Tooltip content="Choose what evidence and artifacts stay attached to this run.">
          <Info className="text-muted hover:text-secondary size-3 cursor-help transition-colors" />
        </Tooltip>
      </div>
      <div className={ADVANCED_SUBSECTION_CLASS}>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm text-foreground font-semibold">Diagnostics</div>
          <Dropdown<DiagnosticsPreset>
            ariaLabel="Diagnostics preset"
            value={diagnosticsPreset}
            onChange={(next) => {
              if (next === 'lean' || next === 'standard' || next === 'deep_debug') {
                onProfileChange((current) => applyDiagnosticsPreset(current, next));
              }
            }}
            options={[
              { value: 'lean', label: 'Lean' },
              { value: 'standard', label: 'Standard' },
              { value: 'deep_debug', label: 'Deep Debug' },
            ]}
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm text-foreground font-semibold">Network Capture</div>
          <Dropdown<CaptureNetworkMode>
            ariaLabel="Network capture"
            value={runProfile.diagnostics_profile.capture_network}
            onChange={(next) => {
              if (!CAPTURE_NETWORK_OPTIONS.has(next)) return;
              onProfileChange((current) => ({
                ...current,
                diagnostics_profile: {
                  ...current.diagnostics_profile,
                  capture_network: next,
                },
              }));
            }}
            options={[
              { value: 'off', label: 'Off' },
              { value: 'matched_only', label: 'Matched Only' },
              { value: 'all_small_json', label: 'All Small JSON' },
            ]}
          />
        </div>
      </div>
      <div className={ADVANCED_SUBSECTION_CLASS}>
        <SettingSection
          label="Capture HTML"
          description="Persist the page HTML artifact for this run."
          checked={runProfile.diagnostics_profile.capture_html}
          onChange={(next) =>
            onProfileChange((current) => ({
              ...current,
              diagnostics_profile: { ...current.diagnostics_profile, capture_html: next },
            }))
          }
        />
        <SettingSection
          label="Capture Screenshot"
          description="Store browser screenshots when available."
          checked={runProfile.diagnostics_profile.capture_screenshot}
          onChange={(next) =>
            onProfileChange((current) => ({
              ...current,
              diagnostics_profile: {
                ...current.diagnostics_profile,
                capture_screenshot: next,
              },
            }))
          }
        />
        <SettingSection
          label="Capture Response Headers"
          description="Preserve response-header diagnostics."
          checked={runProfile.diagnostics_profile.capture_response_headers}
          onChange={(next) =>
            onProfileChange((current) => ({
              ...current,
              diagnostics_profile: {
                ...current.diagnostics_profile,
                capture_response_headers: next,
              },
            }))
          }
        />
        <SettingSection
          label="Capture Browser Diagnostics"
          description="Keep detailed browser-attempt diagnostics for debugging."
          checked={runProfile.diagnostics_profile.capture_browser_diagnostics}
          onChange={(next) =>
            onProfileChange((current) => ({
              ...current,
              diagnostics_profile: {
                ...current.diagnostics_profile,
                capture_browser_diagnostics: next,
              },
            }))
          }
        />
      </div>
    </section>
  );
}
