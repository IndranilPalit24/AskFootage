// Deleting a camera that has recordings (contract 1.5.0): the demo client and the real client follow the same rule.
import { describe, expect, it } from 'vitest';
import { ApiError, FetchApiClient } from '../../web/src/api/client';
import { MockApiClient } from '../../web/src/api/mockClient';

const NEW_CAMERA = { name: 'Yard', ip: '192.168.1.50', username: 'u', password: 'p', acknowledgeCost: true } as const;

async function failureOf(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error('Expected the call to fail');
}

describe('MockApiClient.deleteCamera', () => {
  it('refuses with 409 camera_has_recordings, the counts and no change, when the camera has recordings', async () => {
    const client = new MockApiClient();
    const error = await failureOf(client.deleteCamera('CAM-001'));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.code).toBe('camera_has_recordings');
    expect(error.message).toBe(
      'This camera has 18 recordings and 0 saved clips. Deleting it would delete them too; confirm to delete the camera together with its recordings.',
    );
    const camera = await client.getCamera('CAM-001');
    expect(camera.recordingCount).toBe(18);
    expect(camera.zoneCount).toBe(2);
  });

  it('counts the camera saved clips, with a singular noun for one', async () => {
    const client = new MockApiClient();
    const clipId = (await client.search({ question: 'person', day: '2026-10-30', camera: 'CAM-001' })).clips[0].id;
    await client.saveClip({ clipId, note: '' });
    const error = await failureOf(client.deleteCamera('CAM-001'));
    expect(error.message).toContain('18 recordings and 1 saved clip.');
  });

  it('treats deleteRecordings false like leaving it out', async () => {
    const client = new MockApiClient();
    const error = await failureOf(client.deleteCamera('CAM-002', { deleteRecordings: false }));
    expect(error.code).toBe('camera_has_recordings');
    expect(error.message).toContain('This camera has 3 recordings and 0 saved clips.');
  });

  it('deletes the camera with its recordings, clips, saved clips and zones when deleteRecordings is true', async () => {
    const client = new MockApiClient();
    const [clip] = (await client.search({ question: 'person', day: '2026-10-30', camera: 'CAM-001' })).clips;
    await client.saveClip({ clipId: clip.id, note: '' });
    await client.deleteCamera('CAM-001', { deleteRecordings: true });
    expect((await client.listCameras()).map((camera) => camera.id)).toEqual(['CAM-002', 'CAM-003']);
    expect((await failureOf(client.getCamera('CAM-001'))).status).toBe(404);
    expect(await client.listZones('CAM-002')).not.toEqual([]);
    expect((await client.listSavedClips()).every((saved) => saved.clip.camera !== 'CAM-001')).toBe(true);
    for (const day of (await client.listDays()).map((item) => item.day)) {
      expect((await client.listRecordings(day)).every((recording) => recording.camera !== 'CAM-001')).toBe(true);
    }
    expect((await failureOf(client.deleteCamera('CAM-001', { deleteRecordings: true }))).status).toBe(404);
  });

  it('deletes a camera without recordings at once, whatever deleteRecordings says', async () => {
    const client = new MockApiClient();
    const first = await client.addCamera(NEW_CAMERA);
    const second = await client.addCamera({ ...NEW_CAMERA, name: 'Yard 2' });
    await client.deleteCamera(first.id);
    await client.deleteCamera(second.id, { deleteRecordings: false });
    expect((await client.listCameras()).map((camera) => camera.id)).toEqual(['CAM-001', 'CAM-002', 'CAM-003']);
  });
});

describe('FetchApiClient.deleteCamera', () => {
  function recorder(status = 204) {
    const urls: string[] = [];
    const fetchImpl = (async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return new Response(null, { status });
    }) as typeof fetch;
    return { urls, client: new FetchApiClient('http://localhost:8000/', fetchImpl) };
  }

  it('adds ?deleteRecordings=true only when asked', async () => {
    const { urls, client } = recorder();
    await client.deleteCamera('CAM-001');
    await client.deleteCamera('CAM-001', {});
    await client.deleteCamera('CAM-001', { deleteRecordings: false });
    await client.deleteCamera('CAM-001', { deleteRecordings: true });
    expect(urls).toEqual([
      'http://localhost:8000/api/cameras/CAM-001',
      'http://localhost:8000/api/cameras/CAM-001',
      'http://localhost:8000/api/cameras/CAM-001',
      'http://localhost:8000/api/cameras/CAM-001?deleteRecordings=true',
    ]);
  });

  it('turns a 409 camera_has_recordings answer into an ApiError with the server message', async () => {
    const body = {
      error: { code: 'camera_has_recordings', message: 'This camera has 2 recordings and 1 saved clip. Confirm.' },
    };
    const fetchImpl = (async () =>
      new Response(JSON.stringify(body), { status: 409, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;
    const client = new FetchApiClient('http://localhost:8000', fetchImpl);
    const error = await failureOf(client.deleteCamera('CAM-001'));
    expect([error.status, error.code, error.message]).toEqual([409, 'camera_has_recordings', body.error.message]);
  });
});
