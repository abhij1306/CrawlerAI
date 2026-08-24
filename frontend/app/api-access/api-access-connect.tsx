import { useState } from 'react';

import { detectDefaultShell } from '@lib/ui/detect-shell';
import { CodeBlock, SectionCard, TabBar } from '@ui/patterns';
import {
  mcpLaunchCommand,
  publicApiBaseUrl,
  restExtractCommand,
  restRequestCommand,
  SHELL_OPTIONS,
  shellLabel,
  type SetupShell,
} from './api-access-commands';

/** Stand-in for the secret, which is unrecoverable after creation. */
const KEY_PLACEHOLDER = 'cai_your_key_here';

/**
 * Always-visible setup commands.
 *
 * The post-creation panel disappears once dismissed, so without this an
 * existing key had no snippet UI at all — you had to create a throwaway key to
 * see how to use the one you already had. Same builders, same tabs, with a
 * placeholder in place of the secret.
 */
export function ApiAccessConnect() {
  const [shell, setShell] = useState<SetupShell>(detectDefaultShell);
  const apiBaseUrl = publicApiBaseUrl();
  const label = shellLabel(shell);

  return (
    <SectionCard
      title="Connect a client"
      description="Swap in your own key. Commands are shown for your platform's shell syntax."
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold tracking-wide text-muted uppercase">Platform</span>
        <TabBar<SetupShell>
          value={shell}
          onChange={setShell}
          compact
          size="sm"
          options={[...SHELL_OPTIONS]}
        />
      </div>
      <CodeBlock
        label={`Test REST API · ${label}`}
        value={restRequestCommand(apiBaseUrl, KEY_PLACEHOLDER, shell)}
      />
      <CodeBlock
        label={`Extract one product · ${label}`}
        value={restExtractCommand(apiBaseUrl, KEY_PLACEHOLDER, shell)}
      />
      <CodeBlock
        label={`Launch local MCP process · ${label}`}
        value={mcpLaunchCommand(apiBaseUrl, KEY_PLACEHOLDER, shell)}
      />
    </SectionCard>
  );
}
