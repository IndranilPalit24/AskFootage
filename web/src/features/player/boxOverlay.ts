import type { BoxPoint, BoxTrack, RecordingBoxes } from '../../api/generated/types';

export interface Size {
  width: number;
  height: number;
}

/** A rectangle in CSS pixels, from the top-left corner of the player element. */
export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** One box to draw over the player. */
export interface OverlayBox extends Rect {
  trackId: number;
  label: string;
  role: BoxTrack['role'];
}

/** How far (in frames) from the current frame a track's nearest detection may be and still be drawn. */
export const FRAME_TOLERANCE = 1;

function isSize(size: Size | null | undefined): size is Size {
  return !!size && size.width > 0 && size.height > 0 && Number.isFinite(size.width) && Number.isFinite(size.height);
}

/**
 * Where the picture is inside a player element that shows it with object-fit: contain: as large as fits,
 * centred, with bars on the two sides that are left over.
 */
export function containRect(container: Size, content: Size): Rect {
  const scale = Math.min(container.width / content.width, container.height / content.height);
  const width = content.width * scale;
  const height = content.height * scale;
  return { left: (container.width - width) / 2, top: (container.height - height) / 2, width, height };
}

/** The video frame number shown at a time (seconds from the start of the recording). */
export function frameAt(currentTime: number, fps: number): number {
  return Math.round(currentTime * fps);
}

/**
 * The track's point for a frame: the exact frame, else the nearest one within FRAME_TOLERANCE.
 * Never a point further away, so a gap in the detections has no box (no extrapolation).
 */
export function pointAt(points: readonly BoxPoint[], frame: number): BoxPoint | null {
  let best: BoxPoint | null = null;
  let bestDistance = FRAME_TOLERANCE + 1;
  for (const point of points) {
    const distance = Math.abs(point.frame - frame);
    if (distance < bestDistance) {
      best = point;
      bestDistance = distance;
      if (distance === 0) break;
    }
  }
  return best;
}

/**
 * The boxes to draw at one moment, in pixels of the player element.
 *
 * - container: the size of the player element. content: the size of the video's own picture
 *   (videoWidth x videoHeight); when it is not known yet the stored frame size stands in for it.
 * - A track is drawn only if it has a point at the current frame (see pointAt).
 * - A person is drawn only when the recording has at least one object track: a person alone is not evidence.
 */
export function boxesAt(
  boxes: RecordingBoxes,
  currentTime: number,
  container: Size,
  content?: Size | null,
): OverlayBox[] {
  const { frameWidth, frameHeight, fps } = boxes;
  if (!isSize(container) || !(frameWidth > 0) || !(frameHeight > 0) || !(fps > 0) || !Number.isFinite(currentTime)) {
    return [];
  }
  if (!boxes.tracks.some((track) => track.role === 'object')) return [];

  const frame = frameAt(currentTime, fps);
  const shown = containRect(container, isSize(content) ? content : { width: frameWidth, height: frameHeight });
  const scaleX = shown.width / frameWidth;
  const scaleY = shown.height / frameHeight;

  const result: OverlayBox[] = [];
  for (const track of boxes.tracks) {
    const point = pointAt(track.points, frame);
    if (!point) continue;
    result.push({
      trackId: track.trackId,
      label: track.label,
      role: track.role,
      left: shown.left + point.x1 * scaleX,
      top: shown.top + point.y1 * scaleY,
      width: (point.x2 - point.x1) * scaleX,
      height: (point.y2 - point.y1) * scaleY,
    });
  }
  return result;
}
