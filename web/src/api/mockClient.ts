// In-memory demo client built from contract/examples. Every instance owns a deep copy of the demo
// dataset, so tests (and the app) can write to it freely. It mirrors the API's rules and errors.

import seedJson from '../../../contract/examples/demo-seed.json';
import statusJson from '../../../contract/examples/status.json';
import { addDays, isIsoDay } from '../lib/dates';
import type { ApiClient } from './client';
import { ApiError } from './errors';
import type {
  Camera,
  Clip,
  DaySummary,
  IsoDay,
  Point,
  Recording,
  RecordingAccepted,
  SavedClip,
  SavedClipCreate,
  SavedClipUpdate,
  SearchRequest,
  SearchResponse,
  Status,
  Zone,
  ZoneCreate,
  ZoneUpdate,
} from './generated/types';

/** demo-seed.json: the full demo dataset. Its recordings carry the extra field camera. */
export interface DemoSeed {
  today: IsoDay;
  cameras: Camera[];
  recordings: Array<Recording & { camera: string }>;
  clips: Clip[];
  zones: Zone[];
  savedClips: SavedClip[];
}

export interface MockApiClientOptions {
  /** Delay before each answer, to make loading states visible in the demo. Default 0. */
  latencyMs?: number;
  /** Overrides status.json's demoMode. */
  demoMode?: boolean;
}

const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
const DEFAULT_CAMERA = 'loading-dock';

const CARRY_WORDS = new Set(['carry', 'carrying', 'carried', 'carries', 'box', 'boxes', 'package', 'packages', 'parcel', 'parcels']);
const DWELL_WORDS = new Set([
  'wait',
  'waiting',
  'waited',
  'stay',
  'stayed',
  'staying',
  'stand',
  'standing',
  'stood',
  'linger',
  'lingering',
  'lingered',
  'loiter',
  'loitering',
  'loitered',
]);
const GENERIC_WORDS = new Set(['person', 'persons', 'someone', 'somebody', 'anyone', 'anybody', 'people']);

const NOTHING_RECOGNISED_NOTE =
  'Nothing in the question was recognised. Try words like carrying, waiting or a zone name.';

function clone<T>(value: T): T {
  if (value === undefined) return value;
  return JSON.parse(JSON.stringify(value)) as T;
}

const WORD = /[a-z0-9]+/g;

function words(text: string): string[] {
  // String.prototype.match with a global regex resets lastIndex, so the hoisted regex is safe to reuse.
  return text.toLowerCase().match(WORD) ?? [];
}

function validation(message: string): ApiError {
  return new ApiError(422, 'validation_error', message);
}

function notFound(message: string): ApiError {
  return new ApiError(404, 'not_found', message);
}

function checkId(id: string, field: string): void {
  if (!ID_PATTERN.test(id)) throw validation(`${field} is not a valid id.`);
}

function checkDay(day: string, field = 'day'): void {
  if (!isIsoDay(day)) throw validation(`${field} must be a date written YYYY-MM-DD.`);
}

function checkNote(note: unknown): string {
  if (typeof note !== 'string') throw validation('note must be text.');
  if (note.length > 500) throw validation('note must be at most 500 characters.');
  return note;
}

function checkZoneFields(name: unknown, points: unknown): { name: string; points: Point[] } {
  if (typeof name !== 'string' || name.trim().length === 0) throw validation('name must not be blank.');
  const trimmed = name.trim();
  if (trimmed.length > 60) throw validation('name must be at most 60 characters.');
  if (!Array.isArray(points) || points.length < 3 || points.length > 50) {
    throw validation('points must hold between 3 and 50 points.');
  }
  for (const point of points) {
    const valid =
      Array.isArray(point) &&
      point.length === 2 &&
      point.every((value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1);
    if (!valid) throw validation('Each point must be [x, y] with both values between 0 and 1.');
  }
  return { name: trimmed, points: clone(points as Point[]) };
}

function stripCamera(recording: Recording & { camera: string }): Recording {
  const { id, day, startTime, lengthSeconds, status } = recording;
  return { id, day, startTime, lengthSeconds, status };
}

function byStartTime(a: { startTime: string; id: string }, b: { startTime: string; id: string }): number {
  return a.startTime.localeCompare(b.startTime) || a.id.localeCompare(b.id);
}

const MILLISECONDS = /\.\d{3}Z$/;

function nowUtc(): string {
  return new Date().toISOString().replace(MILLISECONDS, 'Z');
}

export class MockApiClient implements ApiClient {
  private readonly data: DemoSeed;
  private readonly status: Status;
  private readonly latencyMs: number;
  private sequence = 0;

  constructor(options: MockApiClientOptions = {}) {
    this.data = clone(seedJson as unknown as DemoSeed);
    this.status = clone(statusJson as Status);
    if (options.demoMode !== undefined) this.status.demoMode = options.demoMode;
    this.latencyMs = options.latencyMs ?? 0;
  }

  /** Runs fn after the configured latency and hands back a copy, so callers never share internal state. */
  private async answer<T>(fn: () => T): Promise<T> {
    if (this.latencyMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    }
    return clone(fn());
  }

  private nextId(prefix: string): string {
    this.sequence += 1;
    return `${prefix}-m${String(this.sequence).padStart(4, '0')}`;
  }

  private requireCamera(camera: string): Camera {
    checkId(camera, 'camera');
    const found = this.data.cameras.find((item) => item.id === camera);
    if (!found) throw notFound('Camera not found.');
    return found;
  }

  private recordingsOf(camera: string, day: IsoDay): Array<Recording & { camera: string }> {
    return this.data.recordings.filter((item) => item.camera === camera && item.day === day);
  }

  getStatus(): Promise<Status> {
    return this.answer(() => this.status);
  }

  listDays(camera: string): Promise<DaySummary[]> {
    return this.answer(() => {
      this.requireCamera(camera);
      const days: DaySummary[] = [];
      for (let back = 6; back >= 0; back -= 1) {
        const day = addDays(this.data.today, -back);
        const recordings = this.recordingsOf(camera, day);
        days.push({ day, recordings: recordings.length, ready: recordings.filter((r) => r.status === 'ready').length });
      }
      return days;
    });
  }

  listRecordings(day: IsoDay, camera: string): Promise<Recording[]> {
    return this.answer(() => {
      checkDay(day);
      this.requireCamera(camera);
      return this.recordingsOf(camera, day).toSorted(byStartTime).map(stripCamera);
    });
  }

  addRecording(file: File, day: IsoDay, camera: string = DEFAULT_CAMERA): Promise<RecordingAccepted> {
    return this.answer(() => {
      checkDay(day);
      this.requireCamera(camera);
      if (file.size > MAX_UPLOAD_BYTES) {
        throw new ApiError(413, 'file_too_large', 'The file is larger than 200 MiB, so it cannot be added.');
      }
      const isMp4 = file.type === 'video/mp4' || (file.type === '' && /\.mp4$/i.test(file.name));
      if (!isMp4) {
        throw new ApiError(415, 'unsupported_media_type', 'Only MP4 video files can be added.');
      }
      const id = this.nextId(`rec-${day.slice(5, 7)}${day.slice(8, 10)}`);
      this.data.recordings.push({ id, camera, day, startTime: '00:00:00', lengthSeconds: 0, status: 'waiting' });
      return { id, status: 'waiting' as const };
    });
  }

  /** The demo has no footage files, so there is never a video to stream. */
  recordingVideoUrl(recordingId: string): string | null {
    void recordingId;
    return null;
  }

  search(request: SearchRequest): Promise<SearchResponse> {
    return this.answer(() => {
      const question = typeof request.question === 'string' ? request.question.trim() : '';
      if (question.length === 0) throw validation('question must not be blank.');
      if (question.length > 300) throw validation('question must be at most 300 characters.');
      checkDay(request.day);
      this.requireCamera(request.camera);

      const recordings = this.recordingsOf(request.camera, request.day);
      const readyIds = new Set(recordings.filter((r) => r.status === 'ready').map((r) => r.id));
      const notReady = recordings.filter((r) => r.status !== 'ready');

      const tokens = words(question);
      const phrase = ` ${tokens.join(' ')} `;
      const wantsCarrying = tokens.some((token) => CARRY_WORDS.has(token));
      const wantsDwell = tokens.some((token) => DWELL_WORDS.has(token));
      const zoneNames = this.data.zones
        .filter((zone) => zone.camera === request.camera)
        .map((zone) => zone.name)
        .filter((name) => phrase.includes(` ${words(name).join(' ')} `));
      const generic = tokens.some((token) => GENERIC_WORDS.has(token));
      const recognised = wantsCarrying || wantsDwell || zoneNames.length > 0 || generic;

      let clips: Clip[] = [];
      if (recognised) {
        // One pass; every condition the question named must hold.
        clips = this.data.clips
          .filter(
            (clip) =>
              clip.day === request.day &&
              readyIds.has(clip.recordingId) &&
              (!wantsCarrying || clip.evidence.some((item) => item.kind === 'carrying')) &&
              (!wantsDwell || clip.evidence.some((item) => item.kind === 'dwell')) &&
              zoneNames.every((name) => clip.zone === name),
          )
          .toSorted(byStartTime);
      }

      const notes: string[] = [];
      if (!recognised) notes.push(NOTHING_RECOGNISED_NOTE);
      if (notReady.length > 0) {
        const allIndexing = notReady.every((r) => r.status === 'indexing');
        const one = notReady.length === 1;
        const state = allIndexing ? 'still being indexed' : 'not ready yet';
        notes.push(
          one
            ? `1 recording on this day is ${state}, so it was not searched.`
            : `${notReady.length} recordings on this day are ${state}, so they were not searched.`,
        );
      }
      return { question, day: request.day, clips, note: notes.length > 0 ? notes.join(' ') : null };
    });
  }

  getClip(id: string): Promise<Clip> {
    return this.answer(() => {
      checkId(id, 'id');
      const clip = this.data.clips.find((item) => item.id === id);
      if (!clip) throw notFound('Clip not found.');
      return clip;
    });
  }

  listZones(camera?: string): Promise<Zone[]> {
    return this.answer(() => {
      if (camera !== undefined) checkId(camera, 'camera');
      return this.data.zones
        .filter((zone) => camera === undefined || zone.camera === camera)
        .toSorted((a, b) => a.name.localeCompare(b.name));
    });
  }

  private checkNameFree(camera: string, name: string, exceptId?: string): void {
    const taken = this.data.zones.some(
      (zone) => zone.camera === camera && zone.id !== exceptId && zone.name.toLowerCase() === name.toLowerCase(),
    );
    if (taken) throw new ApiError(409, 'zone_name_taken', `A zone called ${name} already exists on this camera.`);
  }

  createZone(body: ZoneCreate): Promise<Zone> {
    return this.answer(() => {
      this.requireCamera(body.camera);
      const { name, points } = checkZoneFields(body.name, body.points);
      this.checkNameFree(body.camera, name);
      const zone: Zone = { id: this.nextId('zone'), camera: body.camera, name, points };
      this.data.zones.push(zone);
      return zone;
    });
  }

  replaceZone(id: string, body: ZoneUpdate): Promise<Zone> {
    return this.answer(() => {
      checkId(id, 'id');
      const zone = this.data.zones.find((item) => item.id === id);
      if (!zone) throw notFound('Zone not found.');
      const { name, points } = checkZoneFields(body.name, body.points);
      this.checkNameFree(zone.camera, name, id);
      zone.name = name;
      zone.points = points;
      return zone;
    });
  }

  deleteZone(id: string): Promise<void> {
    return this.answer(() => {
      checkId(id, 'id');
      const index = this.data.zones.findIndex((item) => item.id === id);
      if (index < 0) throw notFound('Zone not found.');
      this.data.zones.splice(index, 1);
      return undefined;
    });
  }

  listSavedClips(day?: IsoDay): Promise<SavedClip[]> {
    return this.answer(() => {
      if (day !== undefined) checkDay(day);
      return this.data.savedClips
        .filter((saved) => day === undefined || saved.clip.day === day)
        .toSorted((a, b) => b.savedAt.localeCompare(a.savedAt));
    });
  }

  saveClip(body: SavedClipCreate): Promise<SavedClip> {
    return this.answer(() => {
      checkId(body.clipId, 'clipId');
      const note = checkNote(body.note ?? '');
      const clip = this.data.clips.find((item) => item.id === body.clipId);
      if (!clip) throw notFound('Clip not found.');
      if (this.data.savedClips.some((saved) => saved.clip.id === body.clipId)) {
        throw new ApiError(409, 'already_saved', 'This clip is already saved.');
      }
      const saved: SavedClip = { id: this.nextId('saved'), clip: clone(clip), note, savedAt: nowUtc() };
      // Newest first; the stable sort in listSavedClips keeps this order for saves in the same second.
      this.data.savedClips.unshift(saved);
      return saved;
    });
  }

  updateSavedClip(id: string, body: SavedClipUpdate): Promise<SavedClip> {
    return this.answer(() => {
      checkId(id, 'id');
      const note = checkNote(body.note);
      const saved = this.data.savedClips.find((item) => item.id === id);
      if (!saved) throw notFound('Saved clip not found.');
      saved.note = note;
      return saved;
    });
  }

  deleteSavedClip(id: string): Promise<void> {
    return this.answer(() => {
      checkId(id, 'id');
      const index = this.data.savedClips.findIndex((item) => item.id === id);
      if (index < 0) throw notFound('Saved clip not found.');
      this.data.savedClips.splice(index, 1);
      return undefined;
    });
  }
}
