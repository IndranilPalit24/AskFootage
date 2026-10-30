// Time-of-day and duration helpers. Times are HH:MM:SS strings in the camera's local time.

import type { Clip } from '../api/generated/types';

export const SECONDS_PER_DAY = 86_400;

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

/** "10:42:15" -> 38535 */
export function parseTimeOfDay(time: string): number {
  const [hours = 0, minutes = 0, seconds = 0] = time.split(':').map(Number);
  return hours * 3600 + minutes * 60 + seconds;
}

/** 38535 -> "10:42:15" (wraps past midnight). */
export function formatTimeOfDay(totalSeconds: number): string {
  const value = ((Math.floor(totalSeconds) % SECONDS_PER_DAY) + SECONDS_PER_DAY) % SECONDS_PER_DAY;
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return `${pad2(hours)}:${pad2(minutes)}:${pad2(value % 60)}`;
}

/** "06:00:00" -> "06:00" */
export function formatHourMinute(time: string): string {
  return time.slice(0, 5);
}

/** 7200 -> "2 h", 5400 -> "1 h 30 min", 2700 -> "45 min", 40 -> "40 s", 0 -> "—" (not measured yet). */
export function formatLength(totalSeconds: number): string {
  if (totalSeconds <= 0) return '—';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (hours === 0 && minutes === 0) return `${totalSeconds} s`;
  const out: string[] = [];
  if (hours > 0) out.push(`${hours} h`);
  if (minutes > 0) out.push(`${minutes} min`);
  return out.join(' ');
}

/** Wall-clock start of a clip, in seconds since midnight. */
export function clipStartOfDay(clip: Pick<Clip, 'startTime'>): number {
  return parseTimeOfDay(clip.startTime);
}

/** Clip length in seconds. */
export function clipDuration(clip: Pick<Clip, 'startSeconds' | 'endSeconds'>): number {
  return Math.max(0, clip.endSeconds - clip.startSeconds);
}

/** "10:42:15–10:42:31" */
export function formatClipRange(clip: Pick<Clip, 'startTime' | 'startSeconds' | 'endSeconds'>): string {
  const start = clipStartOfDay(clip);
  return `${clip.startTime}–${formatTimeOfDay(start + clipDuration(clip))}`;
}

/** Wall-clock time of a moment in the clip's recording, e.g. a key frame: "10:42:23". */
export function clipMomentTime(clip: Pick<Clip, 'startTime' | 'startSeconds'>, atSeconds: number): string {
  return formatTimeOfDay(clipStartOfDay(clip) + (atSeconds - clip.startSeconds));
}
