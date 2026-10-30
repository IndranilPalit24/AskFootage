// Runs before every UI test file (vite.config.ts -> test.setupFiles).
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

// findBy* / waitFor wait up to 5 s (default 1 s): the first render in a cold worker can take longer.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  // Vitest runs without globals, so Testing Library's automatic cleanup is wired up here.
  cleanup();
  try {
    window.localStorage.clear();
  } catch {
    // No storage in this environment: nothing to clear.
  }
});
