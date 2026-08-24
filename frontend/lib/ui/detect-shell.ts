import type { SetupShell } from '../../app/api-access/api-access-commands';

/**
 * Pick the shell whose syntax matches a platform string.
 *
 * Windows users get PowerShell; everyone else gets bash. When the platform is
 * unknown we fall back to bash rather than guessing Windows, since bash syntax
 * is also what a reader would paste into WSL or a container.
 */
export function defaultShellFor(platform: string | undefined | null): SetupShell {
  if (!platform) return 'bash';
  return /win/i.test(platform) ? 'powershell' : 'bash';
}

type NavigatorWithUserAgentData = Navigator & {
  userAgentData?: { platform?: string };
};

/**
 * Browser wrapper around {@link defaultShellFor}. Guarded so it is safe during
 * SSR and under jsdom, where `navigator` may be absent or bare.
 */
export function detectDefaultShell(): SetupShell {
  if (typeof navigator === 'undefined') return 'bash';
  const nav = navigator as NavigatorWithUserAgentData;
  return defaultShellFor(nav.userAgentData?.platform ?? nav.platform);
}
