import { useCallback, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { Camera } from '../../api/generated/types';
import { usePolling } from '../../hooks/usePolling';

export const CAMERA_REFRESH_MS = 4000;

function sameCamera(a: Camera, b: Camera): boolean {
  return (
    a.id === b.id &&
    a.name === b.name &&
    a.location === b.location &&
    a.department === b.department &&
    a.ip === b.ip &&
    a.status === b.status &&
    a.rtspUrlMasked === b.rtspUrlMasked &&
    a.zoneCount === b.zoneCount &&
    a.recordingCount === b.recordingCount &&
    a.savedClipCount === b.savedClipCount &&
    a.createdAt === b.createdAt
  );
}

/**
 * The server's list, reusing the objects (and the array) that did not change, so a refresh that found
 * nothing new renders nothing.
 */
export function mergeCameras(current: Camera[], fresh: Camera[]): Camera[] {
  const byId = new Map(current.map((camera) => [camera.id, camera]));
  const merged = fresh.map((camera) => {
    const old = byId.get(camera.id);
    return old && sameCamera(old, camera) ? old : camera;
  });
  const unchanged = merged.length === current.length && merged.every((camera, index) => camera === current[index]);
  return unchanged ? current : merged;
}

export interface CameraSync {
  /** True while the last refresh failed; the list on screen is the last good one. */
  refreshFailed: boolean;
  /**
   * Runs a change (add, status, delete). While one runs, and for a refresh that began before it ended, the
   * refresh answer is dropped so it cannot undo what the person just did.
   */
  write: <T>(action: () => Promise<T>) => Promise<T>;
}

/** Keeps the shared camera list fresh: one request at a time, every CAMERA_REFRESH_MS, only while visible. */
export function useCameraSync(
  client: ApiClient,
  setCameras: (update: (current: Camera[]) => Camera[]) => void,
): CameraSync {
  const [refreshFailed, setRefreshFailed] = useState(false);
  const pending = useRef(0);
  const epoch = useRef(0);

  const write = useCallback(async <T,>(action: () => Promise<T>): Promise<T> => {
    pending.current += 1;
    epoch.current += 1;
    try {
      return await action();
    } finally {
      pending.current -= 1;
      epoch.current += 1;
    }
  }, []);

  usePolling(async () => {
    if (pending.current > 0) return;
    const startedAt = epoch.current;
    try {
      const fresh = await client.listCameras();
      if (pending.current > 0 || epoch.current !== startedAt) return;
      setCameras((current) => mergeCameras(current, fresh));
      setRefreshFailed(false);
    } catch {
      setRefreshFailed(true);
    }
  }, CAMERA_REFRESH_MS);

  return { refreshFailed, write };
}
