import { defineConfig, type PluginOption } from 'vite-plus';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production';

export default defineConfig({
  root: frontendRoot,
  plugins: react() as unknown as PluginOption[],
  resolve: {
    alias: {
      '@': path.join(frontendRoot, 'src'),
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
    chunkSizeWarningLimit: 500,
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
            moduleId.includes('/node_modules/@radix-ui/') ||
            moduleId.includes('/node_modules/lucide-react/')
          ) {
            return 'ui';
          }
          if (
            moduleId.includes('/node_modules/react/') ||
            moduleId.includes('/node_modules/react-dom/') ||
            moduleId.includes('/node_modules/scheduler/')
          ) {
            return 'vendor';
          }
          return 'vendor-other';
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: [
      'app/**/*.{test,spec}.{ts,tsx}',
      'components/**/*.{test,spec}.{ts,tsx}',
      'lib/**/*.{test,spec}.{ts,tsx}',
      'src/**/*.{test,spec}.{ts,tsx}',
    ],
    exclude: ['node_modules/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
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
      'jsx-a11y/label-has-associated-control': 'off',
      'jsx-a11y/prefer-tag-over-role': 'off',
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
        files: ['src/routing/image.tsx'],
        rules: {
          'jsx-a11y/alt-text': 'off',
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
