#!/usr/bin/env node
/**
 * Generate `src/lib/types/api.ts` from the canonical OpenAPI contract.
 *
 * Source: `specs/001-private-rag-accelerator/contracts/api-openapi.yaml`
 * Output: `src/lib/types/api.ts`
 *
 * Equivalent to: `openapi-typescript ../../specs/001-private-rag-accelerator/contracts/api-openapi.yaml -o src/lib/types/api.ts`
 *
 * The generated file IS committed; regenerate (and commit) after every
 * contract change. Run via `npm run gen:api`.
 */
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const here = process.cwd();
const spec = resolve(here, '../../specs/001-private-rag-accelerator/contracts/api-openapi.yaml');
const out = resolve(here, 'src/lib/types/api.ts');

const result = spawnSync(
  process.platform === 'win32' ? 'npx.cmd' : 'npx',
  ['--yes', 'openapi-typescript', spec, '-o', out],
  { stdio: 'inherit' }
);

process.exit(result.status ?? 1);
