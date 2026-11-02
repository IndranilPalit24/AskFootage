import type { RecordingBoxes } from '../../api/generated/types';
import { useApiClient } from '../../app/ApiContext';
import { useAsyncData } from '../../hooks/useAsyncData';

/** A recording's stored boxes, or null while loading and when they cannot be loaded (404, offline, empty): no overlay, no error. */
export function useRecordingBoxes(recordingId: string | null): RecordingBoxes | null {
  const client = useApiClient();
  const boxes = useAsyncData(recordingId === null ? null : () => client.getRecordingBoxes(recordingId), ['boxes', recordingId]);
  return boxes.data ?? null;
}
