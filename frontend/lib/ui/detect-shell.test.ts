import { describe, expect, it } from 'vite-plus/test';

import { defaultShellFor } from './detect-shell';

describe('defaultShellFor', () => {
  it('picks PowerShell for Windows platforms', () => {
    expect(defaultShellFor('Win32')).toBe('powershell');
    expect(defaultShellFor('Windows')).toBe('powershell');
    expect(defaultShellFor('WINDOWS')).toBe('powershell');
  });

  it('picks bash for macOS and Linux platforms', () => {
    expect(defaultShellFor('MacIntel')).toBe('bash');
    expect(defaultShellFor('macOS')).toBe('bash');
    expect(defaultShellFor('Linux x86_64')).toBe('bash');
  });

  it('falls back to bash when the platform is unknown', () => {
    // bash syntax is also what a reader pastes into WSL or a container, so it
    // is the safer guess than assuming Windows.
    expect(defaultShellFor(undefined)).toBe('bash');
    expect(defaultShellFor(null)).toBe('bash');
    expect(defaultShellFor('')).toBe('bash');
  });
});
