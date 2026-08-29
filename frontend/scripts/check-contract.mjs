#!/usr/bin/env node

import { spawnSync } from 'node:child_process';

const result = spawnSync('vp', ['test', 'lib/api/contract-drift.test.ts'], {
  stdio: 'inherit',
  shell: true,
  env: { ...process.env, CRAWLERAI_CONTRACT_STRICT: '1' },
});

process.exit(result.status ?? 1);
