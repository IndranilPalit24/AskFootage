// Hand-written TypeScript types for every schema in contract/openapi.yaml (v1.6.0).
// The contract is the source of truth: keep these in step with it, field for field.

/** A calendar date, YYYY-MM-DD. */
export type IsoDay = string;
/** A time of day in the camera's local time, HH:MM:SS. */
export type TimeOfDay = string;

export interface ErrorDetail {
  /**
   * validation_error, not_found, method_not_allowed, already_saved, zone_name_taken, camera_name_taken,
   * file_too_large, unsupported_media_type or internal_error
   */
  code: string;
  /** Plain-English explanation, safe to show to a person; never contains a submitted password. */
  message: string;
}

export interface ErrorBody {
  error: ErrorDetail;
}

export interface Status {
  /** True when the app serves the seeded demo data. Not shown in the UI. */
  demoMode: boolean;
}

/** online: streaming; standby: reachable but not recording; offline: not reachable. */
export type CameraStatus = 'online' | 'standby' | 'offline';

export interface Camera {
  /** CAM-001, CAM-002, ... given by the server in order; never reused. */
  id: string;
  name: string;
  location: string | null;
  department: string | null;
  /** IPv4 address or host name. */
  ip: string;
  status: CameraStatus;
  /** rtsp://<percent-encoded username>:****@<ip>:554/cam/realmonitor?channel=1&subtype=1. Never the password. */
  rtspUrlMasked: string;
  zoneCount: number;
  recordingCount: number;
  savedClipCount: number;
  /** UTC date-time ending in Z. */
  createdAt: string;
}

export interface CameraCreate {
  name: string;
  ip: string;
  username: string;
  /** Write-only: checked by the server, then dropped. Never stored, returned or logged. */
  password: string;
  location?: string | null;
  department?: string | null;
  /** Must be true: the user accepts that searching footage uses their Meta credits. */
  acknowledgeCost: true;
}

export interface CameraUpdate {
  status: CameraStatus;
}

export interface DaySummary {
  day: IsoDay;
  recordings: number;
  ready: number;
}

export type RecordingStatus = 'waiting' | 'preparing' | 'indexing' | 'ready';

export interface Recording {
  id: string;
  /** The id of the camera that made it. */
  camera: string;
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
  /** The id of the camera that made the recording. */
  camera: string;
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
  /** A JPEG of the frame where the match began, with the boxes drawn on it; null when there is none. */
  snapshotUrl: string | null;
}

export interface SearchRequest {
  question: string;
  day: IsoDay;
  /** A camera id; null or left out searches every camera. */
  camera?: string | null;
}

export interface SearchResponse {
  question: string;
  day: IsoDay;
  clips: Clip[];
  note: string | null;
  /** Measured proof for clips found from stored object tracks, one per such clip; empty otherwise. */
  proofs: ClipProof[];
}

export type ProofRelation = 'carrying' | 'in_zone' | 'dwell';

export interface ProofMeasure {
  /** For example frames_together, motion_agreement, frames_inside or coverage. */
  name: string;
  value: number;
}

export interface ProofBox {
  frame: number;
  trackId: number;
  /** A neutral object noun, such as person or cardboard box. */
  label: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface ClipProof {
  /** The clip in clips this proves. */
  clipId: string;
  relation: ProofRelation;
  startFrame: number;
  /** Inclusive. */
  endFrame: number;
  /** Seconds from the start of the recording. */
  startSeconds: number;
  endSeconds: number;
  trackIds: number[];
  trackLabels: string[];
  measures: ProofMeasure[];
  /** First, middle and last box of each track. */
  boxes: ProofBox[];
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

/** One detection of a tracked object, in pixels of the RecordingBoxes frame. */
export interface BoxPoint {
  frame: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface BoxTrack {
  trackId: number;
  /** A neutral object noun, such as person or cardboard box. */
  label: string;
  /** person for a person; object for anything else (drawn highlighted). */
  role: 'person' | 'object';
  /** Ordered by frame; frames without a point had no detection. */
  points: BoxPoint[];
}

/** GET /api/recordings/{id}/boxes: the stored object tracks, for the player to draw boxes live. */
export interface RecordingBoxes {
  recordingId: string;
  /** Width in pixels of the frame the boxes are in. */
  frameWidth: number;
  frameHeight: number;
  /** Frame n is at n / fps seconds. */
  fps: number;
  tracks: BoxTrack[];
}
