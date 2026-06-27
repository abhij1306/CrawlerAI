import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { describe, expect, it } from 'vite-plus/test';

const scriptName = 'check-crawl-architecture.mjs';
const scriptPath = [
  join(process.cwd(), 'scripts', scriptName),
  join(process.cwd(), 'frontend', 'scripts', scriptName),
].find(existsSync);

if (!scriptPath) {
  throw new Error(`Could not locate ${scriptName} from ${process.cwd()}`);
}

const requiredOwnerFiles = [
  'use-crawl-field-actions.ts',
  'use-crawl-domain-memory.ts',
  'use-crawl-route-sync.ts',
  'crawl-advanced-execution.tsx',
  'crawl-advanced-limits.tsx',
  'crawl-advanced-diagnostics.tsx',
];

function writeRequiredOwners(workspace: string) {
  for (const file of requiredOwnerFiles) {
    writeFileSync(join(workspace, 'components', 'crawl', file), 'export {};\n', 'utf8');
  }
}

function writeLazyCrawlPage(workspace: string) {
  writeFileSync(
    join(workspace, 'app', 'crawl', 'page-view.tsx'),
    [
      "const ConfigScreen = lazy(() => import('../../components/crawl/crawl-config-screen'));",
      "const RunScreen = lazy(() => import('../../components/crawl/crawl-run-screen'));",
      'export default function Page() { return <><ConfigScreen /><RunScreen /></>; }',
    ].join('\n'),
    'utf8',
  );
}

describe('check-crawl-architecture', () => {
  it('ignores refetchPanels inside nested template literals', () => {
    const workspace = mkdtempSync(join(tmpdir(), 'crawl-architecture-'));
    try {
      mkdirSync(join(workspace, 'components', 'crawl'), { recursive: true });
      mkdirSync(join(workspace, 'app', 'crawl'), { recursive: true });

      writeFileSync(
        join(workspace, 'components', 'crawl', 'crawl-run-screen.tsx'),
        [
          'const marker = `outer $' + '{condition ? `refetchPanels` : `$' + "{'noop'}`}`;",
          'export function CrawlRunScreen() {',
          '  return <div>{marker}</div>;',
          '}',
        ].join('\n'),
        'utf8',
      );
      writeFileSync(
        join(workspace, 'components', 'crawl', 'crawl-config-screen.tsx'),
        'export function CrawlConfigScreen() { return <div />; }\n',
        'utf8',
      );
      writeRequiredOwners(workspace);
      writeLazyCrawlPage(workspace);

      expect(() => {
        execFileSync(process.execPath, [scriptPath], {
          cwd: workspace,
          stdio: 'pipe',
        });
      }).not.toThrow();
    } finally {
      rmSync(workspace, { recursive: true, force: true });
    }
  });

  it('flags wrapped refetch calls inside setInterval', () => {
    const workspace = mkdtempSync(join(tmpdir(), 'crawl-architecture-'));
    try {
      mkdirSync(join(workspace, 'components', 'crawl'), { recursive: true });
      mkdirSync(join(workspace, 'app', 'crawl'), { recursive: true });

      writeFileSync(
        join(workspace, 'components', 'crawl', 'crawl-run-screen.tsx'),
        [
          'export function CrawlRunScreen() {',
          '  setInterval(() => refetch(), 1000);',
          '  return <div />;',
          '}',
        ].join('\n'),
        'utf8',
      );
      writeFileSync(
        join(workspace, 'components', 'crawl', 'crawl-config-screen.tsx'),
        'export function CrawlConfigScreen() { return <div />; }\n',
        'utf8',
      );
      writeRequiredOwners(workspace);
      writeLazyCrawlPage(workspace);

      expect(() => {
        execFileSync(process.execPath, [scriptPath], {
          cwd: workspace,
          stdio: 'pipe',
        });
      }).toThrow(/must use TanStack Query refetchInterval/);
    } finally {
      rmSync(workspace, { recursive: true, force: true });
    }
  });

  it('flags direct browser-history writes in route synchronization', () => {
    const workspace = mkdtempSync(join(tmpdir(), 'crawl-architecture-'));
    try {
      mkdirSync(join(workspace, 'components', 'crawl'), { recursive: true });
      mkdirSync(join(workspace, 'app', 'crawl'), { recursive: true });
      writeFileSync(
        join(workspace, 'components', 'crawl', 'crawl-run-screen.tsx'),
        'export function CrawlRunScreen() { return <div />; }\n',
        'utf8',
      );
      writeFileSync(
        join(workspace, 'components', 'crawl', 'crawl-config-screen.tsx'),
        'export function CrawlConfigScreen() { return <div />; }\n',
        'utf8',
      );
      writeRequiredOwners(workspace);
      writeFileSync(
        join(workspace, 'components', 'crawl', 'use-crawl-route-sync.ts'),
        "window.history.replaceState(null, '', '/crawl');\n",
        'utf8',
      );
      writeLazyCrawlPage(workspace);

      expect(() => {
        execFileSync(process.execPath, [scriptPath], {
          cwd: workspace,
          stdio: 'pipe',
        });
      }).toThrow(/must use React Router navigation/);
    } finally {
      rmSync(workspace, { recursive: true, force: true });
    }
  });
});
