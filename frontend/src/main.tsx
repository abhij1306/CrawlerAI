import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/geist/index.css';
import '@fontsource-variable/geist-mono/index.css';

import '../app/globals.css';
import { ViteApp } from './router';

const root = document.getElementById('root');

if (!root) {
  throw new Error('Root element #root not found.');
}

createRoot(root).render(
  <StrictMode>
    <ViteApp />
  </StrictMode>,
);
