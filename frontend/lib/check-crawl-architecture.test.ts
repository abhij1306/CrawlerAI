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

const frontendScriptName = 'check-frontend-architecture.mjs';
const frontendScriptPath = [
  join(process.cwd(), 'scripts', frontendScriptName),
  join(process.cwd(), 'frontend', 'scripts', frontendScriptName),
].find(existsSync);

if (!frontendScriptPath) {
  throw new Error(`Could not locate ${frontendScriptName} from ${process.cwd()}`);
}

const requiredOwnerFiles = [
  'use-crawl-field-actions.ts',
  'use-crawl-domain-memory.ts',
  'use-crawl-route-sync.ts',
  'crawl-advanced-execution.tsx',
  'crawl-advanced-limits.tsx',
  'crawl-advanced-diagnostics.tsx',
  'use-run-log-stream.ts',
  'records-table.tsx',
];

function writeRequiredOwners(workspace: string) {
  for (const file of requiredOwnerFiles) {
    writeFileSync(join(workspace, 'components', 'crawl', file), 'export {};\n', 'utf8');
  }
}

function writeCrawlPage(workspace: string) {
  writeFileSync(
    join(workspace, 'app', 'crawl', 'page-view.tsx'),
    [
      "import { CrawlConfigScreen } from '../../components/crawl/crawl-config-screen';",
      "import { CrawlRunScreen } from '../../components/crawl/crawl-run-screen';",
      'export default function Page() { return <><CrawlConfigScreen /><CrawlRunScreen /></>; }',
    ].join('\n'),
    'utf8',
  );
}

const requiredFrontendApiOwners = [
  'admin.ts',
  'api-access.ts',
  'auth.ts',
  'crawls.ts',
  'dashboard.ts',
  'data-enrichment.ts',
  'domain-memory.ts',
  'jobs.ts',
  'knowledge.ts',
  'product-intelligence.ts',
  'selectors.ts',
];

function writeLines(filePath: string, lineCount: number) {
  writeFileSync(filePath, new Array(lineCount).fill('// filler').join('\n'), 'utf8');
}

function writeFrontendArchitectureBase(workspace: string) {
  mkdirSync(join(workspace, 'app', 'data-enrichment'), { recursive: true });
  mkdirSync(join(workspace, 'app', 'runs'), { recursive: true });
  mkdirSync(join(workspace, 'components', 'layout'), { recursive: true });
  mkdirSync(join(workspace, 'lib', 'api'), { recursive: true });
  writeFileSync(join(workspace, 'app', 'data-enrichment', 'page-view.tsx'), 'export {};\n', 'utf8');
  writeFileSync(join(workspace, 'app', 'runs', 'page-view.tsx'), 'export {};\n', 'utf8');
  writeFileSync(join(workspace, 'components', 'layout', 'app-shell.tsx'), 'export {};\n', 'utf8');
  for (const owner of requiredFrontendApiOwners) {
    writeFileSync(join(workspace, 'lib', 'api', owner), 'export {};\n', 'utf8');
  }
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
      writeCrawlPage(workspace);

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
      writeCrawlPage(workspace);

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
      writeCrawlPage(workspace);

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

describe('check-frontend-architecture default LOC cap', () => {
  it('fails for a >400-LOC file not on the exceptions list', () => {
    const workspace = mkdtempSync(join(tmpdir(), 'frontend-architecture-'));
    try {
      writeFrontendArchitectureBase(workspace);
      writeLines(join(workspace, 'lib', 'bloated.ts'), 401);
      // Test files are exempt from the cap.
      writeLines(join(workspace, 'lib', 'bloated.test.ts'), 600);

      expect(() => {
        execFileSync(process.execPath, [frontendScriptPath], {
          cwd: workspace,
          stdio: 'pipe',
        });
      }).toThrow(/lib\/bloated\.ts has 401 lines; limit is 400/);
    } finally {
      rmSync(workspace, { recursive: true, force: true });
    }
  });

  it('passes for a file covered by a measured exception', () => {
    const workspace = mkdtempSync(join(tmpdir(), 'frontend-architecture-'));
    try {
      writeFrontendArchitectureBase(workspace);
      // Over the 400 default cap but under the measured exception budget (525).
      writeLines(join(workspace, 'lib', 'api', 'types.ts'), 520);

      expect(() => {
        execFileSync(process.execPath, [frontendScriptPath], {
          cwd: workspace,
          stdio: 'pipe',
        });
      }).not.toThrow();
    } finally {
      rmSync(workspace, { recursive: true, force: true });
    }
  });
});
