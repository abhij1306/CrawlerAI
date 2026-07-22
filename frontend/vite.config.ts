import { defineConfig, lazyPlugins, loadEnv, type Plugin, type PluginOption } from 'vite-plus';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production';

// connect-src mirrors src/api/client.ts: the VITE_API_BASE_URL origin plus its
// ws(s):// sibling (http:→ws:, https:→wss:). Unset (same-origin deploy) → 'self' only.
function buildContentSecurityPolicy(apiBaseUrl: string | undefined): string {
  const connectSrc = ["'self'"];
  if (apiBaseUrl) {
    try {
      const parsed = new URL(apiBaseUrl);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        const wsProtocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
        connectSrc.push(parsed.origin, `${wsProtocol}//${parsed.host}`);
      }
    } catch {
      // Invalid VITE_API_BASE_URL: app boot rejects it — keep the 'self'-only policy.
    }
  }
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' https: data:",
    "font-src 'self'",
    `connect-src ${connectSrc.join(' ')}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join('; ');
}

// Build-only CSP meta (audit 5.5): injected solely into production builds so the dev
// document stays untouched and HMR keeps working. frame-ancestors cannot be expressed
// in a meta policy and remains owned by the static hosting boundary (see
// docs/frontend-architecture.md runtime notes).
function cspMetaPlugin(): Plugin {
  let contentSecurityPolicy = "default-src 'self'";
  return {
    name: 'csp-meta',
    apply: 'build',
    configResolved(config) {
      const env = loadEnv(config.mode, frontendRoot, 'VITE_');
      contentSecurityPolicy = buildContentSecurityPolicy(env.VITE_API_BASE_URL);
    },
    transformIndexHtml() {
      return [
        {
          tag: 'meta',
          attrs: {
            'http-equiv': 'Content-Security-Policy',
            content: contentSecurityPolicy,
          },
          injectTo: 'head-prepend',
        },
      ];
    },
  };
}

export default defineConfig({
  root: frontendRoot,
  plugins: lazyPlugins(() => [...(react() as PluginOption[]), cspMetaPlugin()]),
  resolve: {
    alias: {
      '@': path.join(frontendRoot, 'src'),
      '@lib': path.join(frontendRoot, 'lib'),
      '@ui': path.join(frontendRoot, 'components', 'ui'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 3000,
  },
  preview: {
    host: '127.0.0.1',
    port: 3000,
  },
  build: {
    target: 'esnext',
    sourcemap: !isProduction,
    cssCodeSplit: true,
    chunkSizeWarningLimit: 350,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replaceAll('\\', '/');
          if (!moduleId.includes('/node_modules/')) return;
          if (moduleId.includes('/node_modules/@tanstack/react-query/')) return 'query';
          if (
            moduleId.includes('/node_modules/react-router-dom/') ||
            moduleId.includes('/node_modules/@remix-run/') ||
            moduleId.includes('/node_modules/react-router/')
          ) {
            return 'router';
          }
          if (
            moduleId.includes('/node_modules/react/') ||
            moduleId.includes('/node_modules/react-dom/') ||
            moduleId.includes('/node_modules/scheduler/')
          ) {
            return 'vendor';
          }
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    pool: 'vmThreads',
    include: [
      'app/**/*.{test,spec}.{ts,tsx}',
      'components/**/*.{test,spec}.{ts,tsx}',
      'lib/**/*.{test,spec}.{ts,tsx}',
      'src/**/*.{test,spec}.{ts,tsx}',
    ],
    exclude: ['node_modules/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json'],
    },
  },
  staged: {
    '*': 'vp check --fix',
  },
  lint: {
    ignorePatterns: ['dist/**', 'node_modules/**', 'coverage/**', 'test-results/**'],
    plugins: ['eslint', 'typescript', 'react', 'jsx-a11y'],
    options: {
      typeAware: true,
      typeCheck: true,
    },
    rules: {
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-useless-escape': 'off',
      '@typescript-eslint/no-empty-object-type': 'off',
      '@typescript-eslint/no-unused-expressions': 'off',
      '@typescript-eslint/no-base-to-string': 'off',
      '@typescript-eslint/no-floating-promises': 'off',
      '@typescript-eslint/no-meaningless-void-operator': 'off',
      '@typescript-eslint/no-redundant-type-constituents': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
        },
      ],
    },
    overrides: [
      {
        files: [
          'components/crawl/form-fields.tsx',
          'components/crawl/records-table.tsx',
          'components/ui/dropdown.tsx',
        ],
        rules: {
          'jsx-a11y/prefer-tag-over-role': 'off',
        },
      },
    ],
  },
  fmt: {
    ignorePatterns: [
      '../backend/**',
      '../docs/**',
      '../agent_debug/**',
      '../.github/**',
      '../.serena/**',
      '*.md',
      '*.toml',
      '*.yml',
      '*.yaml',
      'dist/**',
      'coverage/**',
      'node_modules/**',
      'playwright-report/**',
      'test-results/**',
      '../TEST_SITES.md',
    ],
    semi: true,
    singleQuote: true,
    tabWidth: 2,
    trailingComma: 'all',
    printWidth: 100,
    endOfLine: 'lf',
    sortTailwindcss: {
      stylesheet: './app/globals.css',
    },
  },
});
