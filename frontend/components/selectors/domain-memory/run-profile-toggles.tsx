import type { DomainRunProfile } from '../../../lib/api/types';
import { Toggle } from '../../ui/primitives';
import type { SurfaceWorkspace } from './types';
import type { UpdateProfileDraft } from './profile-types';

type RunProfileTogglesProps = {
  domain: string;
  profile: DomainRunProfile;
  surface: SurfaceWorkspace;
  updateProfileDraft: UpdateProfileDraft;
};

export function RunProfileToggles({
  domain,
  profile,
  surface,
  updateProfileDraft,
}: RunProfileTogglesProps) {
  return (
    <div className="flex flex-col gap-3">
      <ToggleRow
        label="Prefer Browser"
        checked={profile.acquisition_contract.prefer_browser}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            acquisition_contract: { ...current.acquisition_contract, prefer_browser: checked },
          }))
        }
      />
      <ToggleRow
        label="Prefer Curl Handoff"
        checked={profile.acquisition_contract.prefer_curl_handoff}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            acquisition_contract: { ...current.acquisition_contract, prefer_curl_handoff: checked },
          }))
        }
      />
      <ToggleRow
        label="Include iframes"
        checked={profile.fetch_profile.include_iframes}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            fetch_profile: { ...current.fetch_profile, include_iframes: checked },
          }))
        }
      />
      <ToggleRow
        label="Capture HTML"
        checked={profile.diagnostics_profile.capture_html}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            diagnostics_profile: { ...current.diagnostics_profile, capture_html: checked },
          }))
        }
      />
      <ToggleRow
        label="Capture Screenshot"
        checked={profile.diagnostics_profile.capture_screenshot}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            diagnostics_profile: { ...current.diagnostics_profile, capture_screenshot: checked },
          }))
        }
      />
      <ToggleRow
        label="Capture Response Headers"
        checked={profile.diagnostics_profile.capture_response_headers}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            diagnostics_profile: {
              ...current.diagnostics_profile,
              capture_response_headers: checked,
            },
          }))
        }
      />
      <ToggleRow
        label="Capture Browser Diagnostics"
        checked={profile.diagnostics_profile.capture_browser_diagnostics}
        onChange={(checked) =>
          updateProfileDraft(domain, surface, (current) => ({
            ...current,
            diagnostics_profile: {
              ...current.diagnostics_profile,
              capture_browser_diagnostics: checked,
            },
          }))
        }
      />
    </div>
  );
}

type ToggleRowProps = {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
};

function ToggleRow({ checked, label, onChange }: ToggleRowProps) {
  return (
    <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
      <span className="text-sm font-medium">{label}</span>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  );
}
