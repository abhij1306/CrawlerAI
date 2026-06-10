import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { describe, expect, it } from 'vitest';

const scriptPath = join(process.cwd(), 'scripts', 'check-crawl-architecture.mjs');

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
      writeFileSync(
        join(workspace, 'app', 'crawl', 'page.tsx'),
        [
          "import dynamic from 'next/dynamic';",
          "const Screen = dynamic(() => import('../../components/crawl/crawl-run-screen'));",
          'export default function Page() { return <Screen />; }',
        ].join('\n'),
        'utf8',
      );

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
      writeFileSync(
        join(workspace, 'app', 'crawl', 'page.tsx'),
        [
          "import dynamic from 'next/dynamic';",
          "const Screen = dynamic(() => import('../../components/crawl/crawl-run-screen'));",
          'export default function Page() { return <Screen />; }',
        ].join('\n'),
        'utf8',
      );

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
});
