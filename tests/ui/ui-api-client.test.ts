// The real client against a fake fetch: every request must match contract/openapi.yaml exactly.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, createApiClient, FetchApiClient, NETWORK_ERROR_MESSAGE } from '../../web/src/api/client';
import { MockApiClient } from '../../web/src/api/mockClient';

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: BodyInit | null | undefined;
}

function fakeFetch(status: number, body?: unknown) {
  const calls: Call[] = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      method: init?.method ?? 'GET',
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body,
    });
    const text = body === undefined ? null : typeof body === 'string' ? body : JSON.stringify(body);
    return new Response(text, { status, headers: text ? { 'Content-Type': 'application/json' } : {} });
  };
  return { calls, fetchImpl: fetchImpl as typeof fetch };
}

const BASE = 'http://localhost:8000/';

describe('FetchApiClient follows the contract', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('reads with GET on the documented paths and query names', async () => {
    const { calls, fetchImpl } = fakeFetch(200, []);
    const client = new FetchApiClient(BASE, fetchImpl);
    await client.getStatus();
    await client.listDays('CAM-001');
    await client.listRecordings('2026-10-29', 'CAM-001');
    await client.getClip('clip-1029-104215');
    await client.listZones('CAM-001');
    await client.listZones();
    await client.listSavedClips('2026-10-29');
    await client.listSavedClips();
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      'GET http://localhost:8000/api/status',
      'GET http://localhost:8000/api/days?camera=CAM-001',
      'GET http://localhost:8000/api/recordings?day=2026-10-29&camera=CAM-001',
      'GET http://localhost:8000/api/clips/clip-1029-104215',
      'GET http://localhost:8000/api/zones?camera=CAM-001',
      'GET http://localhost:8000/api/zones',
      'GET http://localhost:8000/api/saved-clips?day=2026-10-29',
      'GET http://localhost:8000/api/saved-clips',
    ]);
    for (const call of calls) {
      expect(call.headers).toEqual({ Accept: 'application/json' });
    }
  });

  it('sends JSON bodies for search, zones and saved clips', async () => {
    const { calls, fetchImpl } = fakeFetch(200, {});
    const client = new FetchApiClient(BASE, fetchImpl);
    await client.search({ question: 'someone carrying a box', day: '2026-10-29', camera: 'CAM-001' });
    await client.replaceZone('zone-exit-lane', { name: 'Exit gate', points: [[0, 0], [1, 0], [1, 1]] });
    await client.updateSavedClip('saved-1', { note: 'Checked' });
    expect(calls.map((call) => [call.method, call.url, JSON.parse(String(call.body))])).toEqual([
      ['POST', 'http://localhost:8000/api/search', { question: 'someone carrying a box', day: '2026-10-29', camera: 'CAM-001' }],
      ['PUT', 'http://localhost:8000/api/zones/zone-exit-lane', { name: 'Exit gate', points: [[0, 0], [1, 0], [1, 1]] }],
      ['PATCH', 'http://localhost:8000/api/saved-clips/saved-1', { note: 'Checked' }],
    ]);
    for (const call of calls) {
      expect(call.headers).toEqual({ Accept: 'application/json', 'Content-Type': 'application/json' });
    }
  });

  it('reads the body of 201 Created', async () => {
    const zone = { id: 'zone-1', camera: 'CAM-001', name: 'Dock edge', points: [[0, 0], [1, 0], [1, 1]] };
    const { calls, fetchImpl } = fakeFetch(201, zone);
    const client = new FetchApiClient(BASE, fetchImpl);
    await expect(client.createZone({ camera: 'CAM-001', name: 'Dock edge', points: zone.points as [number, number][] })).resolves.toEqual(zone);
    await client.saveClip({ clipId: 'clip-1029-104215', note: '' });
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      'POST http://localhost:8000/api/zones',
      'POST http://localhost:8000/api/saved-clips',
    ]);
    expect(JSON.parse(String(calls[1].body))).toEqual({ clipId: 'clip-1029-104215', note: '' });
  });

  it('uploads footage as multipart (file, day, camera) and reads the 202 body', async () => {
    const { calls, fetchImpl } = fakeFetch(202, { id: 'rec-1030-a41f', status: 'waiting' });
    const client = new FetchApiClient(BASE, fetchImpl);
    const file = new File(['x'], 'dock.mp4', { type: 'video/mp4' });
    await expect(client.addRecording(file, '2026-10-30', 'CAM-001')).resolves.toEqual({ id: 'rec-1030-a41f', status: 'waiting' });
    const [call] = calls;
    expect(`${call.method} ${call.url}`).toBe('POST http://localhost:8000/api/recordings');
    // No Content-Type: the browser writes the multipart boundary itself.
    expect(call.headers).toEqual({ Accept: 'application/json' });
    const form = call.body as FormData;
    expect((form.get('file') as File).name).toBe('dock.mp4');
    expect(form.get('day')).toBe('2026-10-30');
    expect(form.get('camera')).toBe('CAM-001');
  });

  it('treats 204 No Content as done', async () => {
    const { calls, fetchImpl } = fakeFetch(204);
    const client = new FetchApiClient(BASE, fetchImpl);
    await expect(client.deleteZone('zone-exit-lane')).resolves.toBeUndefined();
    await expect(client.deleteSavedClip('saved-1')).resolves.toBeUndefined();
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      'DELETE http://localhost:8000/api/zones/zone-exit-lane',
      'DELETE http://localhost:8000/api/saved-clips/saved-1',
    ]);
  });

  it('turns the standard error body into an ApiError with its status, code and message', async () => {
    const { fetchImpl } = fakeFetch(409, { error: { code: 'already_saved', message: 'This clip is already saved.' } });
    const error = await new FetchApiClient(BASE, fetchImpl).saveClip({ clipId: 'clip-1' }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'already_saved', message: 'This clip is already saved.' });
  });

  it('falls back to a safe message when the error body is not the standard one', async () => {
    const { fetchImpl } = fakeFetch(502, '<html>Bad gateway</html>');
    const error = await new FetchApiClient(BASE, fetchImpl).getStatus().catch((caught: unknown) => caught);
    expect(error).toMatchObject({ status: 502, code: 'internal_error', message: 'The server could not answer (HTTP 502). Try again.' });
  });

  it('reports an unreachable server without details', async () => {
    const client = new FetchApiClient(BASE, (() => Promise.reject(new TypeError('Failed to fetch'))) as typeof fetch);
    await expect(client.getStatus()).rejects.toMatchObject({ status: 0, code: 'network_error', message: NETWORK_ERROR_MESSAGE });
  });

  it('builds the video URL from the base URL', () => {
    expect(new FetchApiClient(BASE).recordingVideoUrl('rec-1029-1030')).toBe('http://localhost:8000/api/recordings/rec-1029-1030/video');
  });

  it('reads the boxes of a recording with GET /api/recordings/{id}/boxes', async () => {
    const body = { recordingId: 'clip2', frameWidth: 1920, frameHeight: 1080, fps: 5, tracks: [] };
    const { calls, fetchImpl } = fakeFetch(200, body);
    expect(await new FetchApiClient(BASE, fetchImpl).getRecordingBoxes('clip2')).toEqual(body);
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual(['GET http://localhost:8000/api/recordings/clip2/boxes']);
  });

  it('uses the real client only when VITE_API_URL is set, and the demo client otherwise', () => {
    vi.stubEnv('VITE_API_URL', 'http://localhost:8000');
    expect(createApiClient()).toBeInstanceOf(FetchApiClient);
    vi.stubEnv('VITE_API_URL', '');
    expect(createApiClient()).toBeInstanceOf(MockApiClient);
  });
});

describe('front-end code holds no secrets', () => {
  const sources = import.meta.glob('../../web/src/**/*.{ts,tsx,css}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

  it('scans every source file', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(30);
  });

  // The camera stream password is a write-only field the user types (contract: CameraCreate.password). These
  // exact lines name it without holding any value; every other mention is still an offender.
  const ALLOWED_LINES: Record<string, string> = {
    // The contract's type for the field: no value.
    '../../web/src/api/generated/types.ts': 'password: string;',
    // The demo client checks the length of what was sent, then drops it.
    '../../web/src/api/mockClient.ts': "const secretLength = typeof body.password === 'string' ? body.password.length : 0;",
    // The Add camera form puts what the user typed into the request body.
    '../../web/src/features/cameras/cameraForm.ts': 'password: values.streamSecret,',
  };

  it('has no API key, token or auth header anywhere', () => {
    const patterns = [
      /\b(api[_-]?key|secret|access[_-]?token|password)\b['"]?\s*[:=]/i, // a key or secret being set
      /['"](authorization|x-api-key)['"]\s*:/i, // an auth header
      /\bbearer\s+[a-z0-9]/i,
      /\bsk-[a-z0-9]{8}/i,
    ];
    const offenders = Object.entries(sources)
      .map(([path, text]) => [path, text.split('\n').filter((line) => line.trim() !== ALLOWED_LINES[path]).join('\n')])
      .filter(([, text]) => patterns.some((pattern) => pattern.test(text)))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it('allows each stream password line exactly once, so the allowance cannot grow unnoticed', () => {
    for (const [path, allowed] of Object.entries(ALLOWED_LINES)) {
      const count = (sources[path] ?? '').split('\n').filter((line) => line.trim() === allowed).length;
      expect(`${path}: ${count}`).toBe(`${path}: 1`);
    }
  });

  it('reads no environment variable other than VITE_API_URL', () => {
    const names = Object.values(sources).flatMap((text) => [...text.matchAll(/import\.meta\.env\.([A-Z_]+)/g)].map((match) => match[1]));
    expect(new Set(names)).toEqual(new Set(['VITE_API_URL']));
  });
});

describe('MockApiClient mirrors the API (demo mode)', () => {
  it('gives every instance its own copy of the demo data', async () => {
    const first = new MockApiClient();
    const second = new MockApiClient();
    await first.deleteZone('zone-exit-lane');
    expect(await first.listZones('CAM-001')).toHaveLength(1);
    expect(await second.listZones('CAM-001')).toHaveLength(2);
  });

  it("answers the 7 days ending on the server's today, with Thu 29 as in the design reference", async () => {
    const client = new MockApiClient();
    const days = await client.listDays('CAM-001');
    expect(days.map((entry) => entry.day)).toEqual([
      '2026-10-24',
      '2026-10-25',
      '2026-10-26',
      '2026-10-27',
      '2026-10-28',
      '2026-10-29',
      '2026-10-30',
    ]);
    expect(days[5]).toEqual({ day: '2026-10-29', recordings: 6, ready: 5 });
    const thursday = await client.listRecordings('2026-10-29', 'CAM-001');
    expect(thursday.map((recording) => recording.id)).toEqual([
      'rec-1029-0600',
      'rec-1029-0705',
      'rec-1029-0912',
      'rec-1029-1030',
      'rec-1029-1300',
      'rec-1029-1610',
    ]);
  });

  it('matches questions with simple keywords, like the backend', async () => {
    const client = new MockApiClient();
    const ask = async (question: string, day = '2026-10-29') =>
      (await client.search({ question, day, camera: 'CAM-001' })).clips.map((clip) => clip.id);
    expect(await ask('someone carrying a box')).toHaveLength(5);
    expect(await ask('someone waiting by the exit lane')).toEqual(['clip-1029-072140', 'clip-1029-131430']);
    expect(await ask('people carrying boxes through the loading door')).toEqual([
      'clip-1029-061405',
      'clip-1029-070903',
      'clip-1029-104215',
      'clip-1029-130610',
    ]);
    expect(await ask('someone')).toHaveLength(8);
    const nothing = await client.search({ question: 'a bicycle', day: '2026-10-28', camera: 'CAM-001' });
    expect(nothing.clips).toEqual([]);
    expect(nothing.note).toMatch(/Nothing in the question was recognised/);
    const fullyReady = await client.search({ question: 'someone', day: '2026-10-28', camera: 'CAM-001' });
    expect(fullyReady.note).toBeNull();
  });

  it('raises the contract errors and serves no video in demo mode', async () => {
    const client = new MockApiClient();
    await expect(client.getClip('clip-missing')).rejects.toMatchObject({ status: 404, code: 'not_found' });
    await expect(client.search({ question: '  ', day: '2026-10-29', camera: 'CAM-001' })).rejects.toMatchObject({
      status: 422,
      code: 'validation_error',
    });
    await client.saveClip({ clipId: 'clip-1029-104215' });
    await expect(client.saveClip({ clipId: 'clip-1029-104215' })).rejects.toMatchObject({ status: 409, code: 'already_saved' });
    await expect(
      client.createZone({ camera: 'CAM-001', name: 'Exit lane', points: [[0, 0], [1, 0], [1, 1]] }),
    ).rejects.toMatchObject({ status: 409, code: 'zone_name_taken' });
    await expect(
      client.createZone({ camera: 'CAM-001', name: 'Two points', points: [[0, 0], [1, 0]] }),
    ).rejects.toMatchObject({ code: 'validation_error' });
    expect(client.recordingVideoUrl('rec-1029-1030')).toBeNull();
  });
});
