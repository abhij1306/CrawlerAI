import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const root = process.cwd();

const checks = [
  {
    file: 'components/crawl/crawl-run-screen.tsx',
    maxLines: 400,
  },
  {
    file: 'components/crawl/crawl-config-screen.tsx',
    maxLines: 350,
  },
  {
    file: 'components/crawl/use-crawl-field-actions.ts',
    maxLines: 230,
  },
  {
    file: 'components/crawl/use-crawl-domain-memory.ts',
    maxLines: 210,
  },
  {
    file: 'components/crawl/crawl-advanced-execution.tsx',
    maxLines: 220,
  },
  {
    file: 'components/crawl/crawl-advanced-limits.tsx',
    maxLines: 190,
  },
  {
    file: 'components/crawl/crawl-advanced-diagnostics.tsx',
    maxLines: 170,
  },
];

const failures = [];
const fileCache = new Map();

function read(relativePath) {
  if (fileCache.has(relativePath)) {
    return fileCache.get(relativePath);
  }
  try {
    const content = fs.readFileSync(path.join(root, relativePath), 'utf8');
    fileCache.set(relativePath, content);
    return content;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    failures.push(`${relativePath} could not be read: ${message}`);
    fileCache.set(relativePath, null);
    return null;
  }
}

function dynamicallyImportsHeavyCrawlScreens(content) {
  const source = ts.createSourceFile(
    'app/crawl/page-view.tsx',
    content,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const requiredImports = new Set([
    '../../components/crawl/crawl-config-screen',
    '../../components/crawl/crawl-run-screen',
  ]);
  const discoveredImports = new Set();

  function visit(node) {
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length === 1 &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      discoveredImports.add(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  }

  visit(source);
  return [...requiredImports].some((modulePath) => discoveredImports.has(modulePath));
}

function findNextRouterArtifacts() {
  const appRoot = path.join(root, 'app');
  const artifacts = [];
  if (!fs.existsSync(appRoot)) {
    return artifacts;
  }
  function walk(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const relativePath = path.relative(root, fullPath).replaceAll('\\', '/');
      if (entry.isDirectory()) {
        if (/^\[.+\]$/.test(entry.name)) {
          artifacts.push(relativePath);
        }
        walk(fullPath);
        continue;
      }
      if (entry.isFile() && /^(loading|layout|error|not-found)\.tsx?$/.test(entry.name)) {
        artifacts.push(relativePath);
      }
    }
  }
  walk(appRoot);
  return artifacts;
}

function hasManualDateNowFieldId(content) {
  return /(?:id|field|manual).{0,60}?Date\.now\(\)|Date\.now\(\).{0,60}?(?:id|field|manual)|current\.length.{0,60}?(?:id|field|manual)|(?:id|field|manual).{0,60}?current\.length/i.test(
    content,
  );
}

function maskNonNewlines(text) {
  return text.replace(/[^\n]/g, ' ');
}

function scanQuotedString(content, start, quote) {
  let index = start + 1;
  let masked = ' ';
  while (index < content.length) {
    const char = content[index];
    masked += char === '\n' ? '\n' : ' ';
    if (char === '\\') {
      index += 1;
      if (index < content.length) {
        masked += content[index] === '\n' ? '\n' : ' ';
      }
    } else if (char === quote) {
      return { end: index + 1, masked };
    }
    index += 1;
  }
  return { end: content.length, masked };
}

function scanTemplateLiteral(content, start) {
  let index = start + 1;
  let masked = ' ';
  while (index < content.length) {
    const char = content[index];
    if (char === '`') {
      masked += ' ';
      return { end: index + 1, masked };
    }
    if (char === '\\') {
      masked += ' ';
      index += 1;
      if (index < content.length) {
        masked += content[index] === '\n' ? '\n' : ' ';
      }
      index += 1;
      continue;
    }
    if (char === '$' && content[index + 1] === '{') {
      masked += '  ';
      index += 2;
      let depth = 1;
      while (index < content.length && depth > 0) {
        const inner = content[index];
        if (inner === "'" || inner === '"') {
          const scanned = scanQuotedString(content, index, inner);
          masked += scanned.masked;
          index = scanned.end;
          continue;
        }
        if (inner === '`') {
          const scanned = scanTemplateLiteral(content, index);
          masked += scanned.masked;
          index = scanned.end;
          continue;
        }
        masked += inner === '\n' ? '\n' : ' ';
        if (inner === '{') {
          depth += 1;
        } else if (inner === '}') {
          depth -= 1;
        } else if (inner === '\\') {
          index += 1;
          if (index < content.length) {
            masked += content[index] === '\n' ? '\n' : ' ';
          }
        }
        index += 1;
      }
      continue;
    }
    masked += char === '\n' ? '\n' : ' ';
    index += 1;
  }
  return { end: content.length, masked };
}

function stripTemplateLiterals(content) {
  let output = '';
  let index = 0;
  while (index < content.length) {
    if (content[index] !== '`') {
      output += content[index];
      index += 1;
      continue;
    }
    const scanned = scanTemplateLiteral(content, index);
    output += scanned.masked;
    index = scanned.end;
  }
  return output;
}

function stripCommentsAndStrings(content) {
  return stripTemplateLiterals(content)
    .replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, ' '))
    .replace(/\/\/.*$/gm, '')
    .replace(/'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g, maskNonNewlines);
}

for (const check of checks) {
  const content = read(check.file);
  if (content === null) {
    continue;
  }
  const lines = content.split(/\r?\n/).length;
  if (lines > check.maxLines) {
    failures.push(`${check.file} has ${lines} lines; limit is ${check.maxLines}. Split the owner.`);
  }
}

const runScreen = read('components/crawl/crawl-run-screen.tsx');
const cleanedRunScreen = runScreen === null ? null : stripCommentsAndStrings(runScreen);
if (
  cleanedRunScreen !== null &&
  /\brefetchPanels\b|(?:\bwindow\.)?\bsetInterval\s*\([\s\S]*?\brefetch\b/.test(cleanedRunScreen)
) {
  failures.push(
    'components/crawl/crawl-run-screen.tsx must use TanStack Query refetchInterval for server polling.',
  );
}
if (
  cleanedRunScreen !== null &&
  /\buseQuery\s*\(|\bnew\s+WebSocket\s*\(|\bapi\s*\./.test(cleanedRunScreen)
) {
  failures.push(
    'components/crawl/crawl-run-screen.tsx must delegate queries, websocket transport, and API mutations to feature hooks.',
  );
}
if (cleanedRunScreen !== null && /\bestimateDataQuality\b/.test(cleanedRunScreen)) {
  failures.push(
    'components/crawl/crawl-run-screen.tsx must consume backend quality instead of estimating semantic quality in the page owner.',
  );
}

const configScreen = read('components/crawl/crawl-config-screen.tsx');
const cleanedConfigScreen = configScreen === null ? null : stripCommentsAndStrings(configScreen);
if (configScreen !== null && hasManualDateNowFieldId(configScreen)) {
  failures.push(
    'components/crawl/crawl-config-screen.tsx must not build manual field IDs from Date.now/current.length.',
  );
}
if (
  cleanedConfigScreen !== null &&
  /\buseQuery\s*\(|\bapi\s*\.|\buseLayoutEffect\s*\(|\bwindow\.sessionStorage\b/.test(
    cleanedConfigScreen,
  )
) {
  failures.push(
    'components/crawl/crawl-config-screen.tsx must delegate queries, API mutations, and route-prefill synchronization to feature hooks.',
  );
}

const crawlPage = read('app/crawl/page-view.tsx');
if (crawlPage !== null && dynamicallyImportsHeavyCrawlScreens(crawlPage)) {
  failures.push(
    'app/crawl/page-view.tsx must not add a second lazy boundary around crawl-config-screen or crawl-run-screen.',
  );
}

const nextRouterArtifacts = findNextRouterArtifacts();
if (nextRouterArtifacts.length) {
  failures.push(
    `React Router owns routes; remove Next App Router-only artifacts: ${nextRouterArtifacts.join(', ')}.`,
  );
}

const routeSync = read('components/crawl/use-crawl-route-sync.ts');
const cleanedRouteSync = routeSync === null ? null : stripCommentsAndStrings(routeSync);
if (
  cleanedRouteSync !== null &&
  /\bhistory\s*\.\s*(?:pushState|replaceState)\s*\(/.test(cleanedRouteSync)
) {
  failures.push(
    'components/crawl/use-crawl-route-sync.ts must use React Router navigation instead of writing browser history directly.',
  );
}

if (failures.length) {
  console.error('Crawl architecture check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}
