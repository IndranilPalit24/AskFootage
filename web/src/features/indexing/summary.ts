import type { Recording, RecordingStatus } from '../../api/generated/types';
import { formatLength } from '../../lib/time';

function recordingsCount(count: number): string {
  return count === 1 ? '1 recording' : `${count} recordings`;
}

/**
 * The Camera screen's summary line, computed from the day's recordings:
 * "6 recordings · 2 h 14 min · 5 ready". The length is left out while nothing has been measured
 * (new uploads have length 0); a day without footage reads "No recordings".
 */
export function recordingsSummary(recordings: readonly Recording[]): string {
  if (recordings.length === 0) return 'No recordings';
  let totalSeconds = 0;
  let ready = 0;
  for (const recording of recordings) {
    totalSeconds += recording.lengthSeconds;
    if (recording.status === 'ready') ready += 1;
  }
  const parts = [recordingsCount(recordings.length)];
  if (totalSeconds > 0) parts.push(formatLength(totalSeconds));
  parts.push(`${ready} ready`);
  return parts.join(' · ');
}

export const STATUS_LABEL: Record<RecordingStatus, string> = {
  ready: 'Ready',
  indexing: 'Indexing',
  preparing: 'Preparing',
  waiting: 'Waiting',
};

/** The note a row shows instead of Open while its recording is not searchable yet. */
export const STATUS_NOTE: Record<Exclude<RecordingStatus, 'ready'>, string> = {
  waiting: 'Not uploaded yet',
  preparing: 'Almost there',
  indexing: 'Nearly searchable',
};
