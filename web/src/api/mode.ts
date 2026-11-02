// Which API the app talks to. Chosen explicitly and the same way every time: never a silent fallback.
//
//   VITE_API_URL=http://localhost:8000   the real API (the normal case)
//   VITE_API_MODE=mock                   the in-memory demo client, on purpose (no footage, no server)
//   neither set                          not configured: the app says so instead of pretending
//   both set, or an unknown mode/URL     not configured, with the reason

export type ApiChoice =
  | { kind: 'api'; baseUrl: string }
  | { kind: 'mock' }
  | { kind: 'unconfigured'; reason: string };

export interface ApiEnv {
  VITE_API_URL?: string;
  VITE_API_MODE?: string;
}

export function resolveApiChoice(env: ApiEnv): ApiChoice {
  const url = (env.VITE_API_URL ?? '').trim();
  const mode = (env.VITE_API_MODE ?? '').trim().toLowerCase();
  if (mode !== '' && mode !== 'api' && mode !== 'mock') {
    return { kind: 'unconfigured', reason: `VITE_API_MODE is "${mode}"; it must be "api" or "mock".` };
  }
  if (mode === 'mock') {
    if (url !== '') return { kind: 'unconfigured', reason: 'VITE_API_MODE=mock and VITE_API_URL are both set. Set only one.' };
    return { kind: 'mock' };
  }
  if (url === '') return { kind: 'unconfigured', reason: 'VITE_API_URL is not set.' };
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') throw new Error('protocol');
  } catch {
    return { kind: 'unconfigured', reason: `VITE_API_URL ("${url}") is not an http or https address.` };
  }
  return { kind: 'api', baseUrl: url };
}
