import react from '@vitejs/plugin-react';
import path from 'node:path';
import { defineConfig } from 'vite';

const root = __dirname;
const isProduction = process.env.NODE_ENV === 'production';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(root, 'src'),
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
          if (moduleId.includes('/node_modules/')) {
            if (moduleId.includes('/node_modules/@tanstack/react-query/')) {
              return 'query';
            }
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
          }
        },
      },
    },
  },
});
