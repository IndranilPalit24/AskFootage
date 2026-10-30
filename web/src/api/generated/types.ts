// Hand-written TypeScript types for every schema in contract/openapi.yaml (v1.0.0).
// The contract is the source of truth: keep these in step with it, field for field.

/** A calendar date, YYYY-MM-DD. */
export type IsoDay = string;
/** A time of day in the camera's local time, HH:MM:SS. */
export type TimeOfDay = string;

export interface ErrorDetail {
  /** validation_error, not_found, already_saved, zone_name_taken, file_too_large, unsupported_media_type or internal_error */
  code: string;
  /** Plain-English explanation, safe to show to a person. */
  message: string;
}

export interface ErrorBody {
  error: ErrorDetail;
}

export interface Camera {
  id: string;
  name: string;
}

export interface Status {
  demoMode: boolean;
  camera: Camera;
}

export interface DaySummary {
  day: IsoDay;
  recordings: number;
  ready: number;
}

export type RecordingStatus = 'waiting' | 'preparing' | 'indexing' | 'ready';

export interface Recording {
  id: string;
  day: IsoDay;
  startTime: TimeOfDay;
  lengthSeconds: number;
  status: RecordingStatus;
}

export interface RecordingAccepted {
  id: string;
  status: 'waiting';
}

export type EvidenceKind = 'carrying' | 'in_zone' | 'dwell';

export interface Evidence {
  kind: EvidenceKind;
  /** Short chip text, for example "Carrying · 16 s". */
  text: string;
}

export interface KeyFrame {
  /** Seconds from the start of the recording. */
  atSeconds: number;
  imageUrl: string | null;
}

export interface Clip {
  id: string;
  recordingId: string;
  day: IsoDay;
  startTime: TimeOfDay;
  /** Seconds from the start of the recording. */
  startSeconds: number;
  /** Seconds from the start of the recording; greater than startSeconds. */
  endSeconds: number;
  label: string;
  evidence: Evidence[];
  zone: string | null;
  whyMatched: string;
  keyFrames: KeyFrame[];
  thumbnailUrl: string | null;
}

export interface SearchRequest {
  question: string;
  day: IsoDay;
  camera: string;
}

export interface SearchResponse {
  question: string;
  day: IsoDay;
  clips: Clip[];
  note: string | null;
}

/** [x, y] as fractions (0..1) of the frame's width and height, from the top-left corner. */
export type Point = [number, number];

export interface Zone {
  id: string;
  camera: string;
  name: string;
  points: Point[];
}

export interface ZoneCreate {
  camera: string;
  name: string;
  points: Point[];
}

export interface ZoneUpdate {
  name: string;
  points: Point[];
}

export interface SavedClip {
  id: string;
  clip: Clip;
  note: string;
  /** UTC date-time ending in Z. */
  savedAt: string;
}

export interface SavedClipCreate {
  clipId: string;
  note?: string;
}

export interface SavedClipUpdate {
  note: string;
}
