/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const webDir = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = fileURLToPath(new URL('..', import.meta.url));
// The demo client reads the contract's example JSON, which lives outside web/.
const contractExamples = fileURLToPath(new URL('../contract/examples', import.meta.url));
const uiTests = fileURLToPath(new URL('../tests/ui', import.meta.url));

export default defineConfig({
  root: webDir,
  plugins: [react()],
  resolve: {
    // Test files live in tests/ui, outside web/: resolve these from web/node_modules (the project root)
    // so there is exactly one copy of React and the testing libraries.
    dedupe: ['react', 'react-dom', 'react-router-dom', 'react-router', '@testing-library/react', '@testing-library/dom'],
  },
  server: {
    fs: {
      allow: [webDir, contractExamples, uiTests],
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    root: webDir,
    dir: repoRoot,
    include: ['tests/ui/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
    // Worker threads: the forks pool did not start within its timeout on this Windows machine.
    pool: 'threads',
    // jsdom + role queries are slow on a cold, busy machine: generous limits instead of flaky timeouts.
    testTimeout: 30_000,
    // Vitest blanks CSS imports by default; the design-token test reads global.css (?raw) to check it.
    css: { include: [/global\.css/] },
    setupFiles: [fileURLToPath(new URL('../tests/ui/setup-ui-tests.ts', import.meta.url))],
  },
});
