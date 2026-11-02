import { ApiError, apiErrorFromResponse, NETWORK_ERROR_MESSAGE } from './errors';
import type {
  Camera,
  CameraCreate,
  CameraUpdate,
  Clip,
  ConceptJob,
  ConceptRequest,
  DaySummary,
  IsoDay,
  Recording,
  RecordingAccepted,
  RecordingBoxes,
  SavedClip,
  SavedClipCreate,
  SavedClipUpdate,
  SearchRequest,
  SearchResponse,
  DemoCodeAccepted,
  Status,
  Zone,
  ZoneCreate,
  ZoneUpdate,
} from './generated/types';
import { MockApiClient } from './mockClient';
import { resolveApiChoice, type ApiChoice } from './mode';

export interface DeleteCameraOptions {
  deleteRecordings?: boolean;
}

/** One method per operation in contract/openapi.yaml. */
export interface ApiClient {
  getStatus(): Promise<Status>;
  /**
   * A demo gate for the UI only (it protects nothing). 200 {ok:true}; 401 invalid_demo_code "That code is not valid.";
   * 422 for a body that is not 6 digits; 429 too_many_attempts. The code is never stored or logged.
   */
  checkDemoCode(code: string): Promise<DemoCodeAccepted>;
  /** In id order. */
  listCameras(): Promise<Camera[]>;
  getCamera(id: string): Promise<Camera>;
  /** 201 with the new camera; 409 camera_name_taken when the name is in use, ignoring case. */
  addCamera(body: CameraCreate): Promise<Camera>;
  updateCamera(id: string, body: CameraUpdate): Promise<Camera>;
  /**
   * A camera with no recordings is deleted at once. With recordings the answer is 409 camera_has_recordings
   * (nothing changes) unless options.deleteRecordings is true, which also removes its recordings, clips,
   * saved clips and zones.
   */
  deleteCamera(id: string, options?: DeleteCameraOptions): Promise<void>;
  /** Without camera: the counts cover all cameras. */
  listDays(camera?: string): Promise<DaySummary[]>;
  /** Without camera: every camera's recordings. */
  listRecordings(day: IsoDay, camera?: string): Promise<Recording[]>;
  addRecording(file: File, day: IsoDay, camera: string): Promise<RecordingAccepted>;
  /** The stored object tracks of a recording, to draw boxes over the playing video. 404 when the recording is unknown. */
  getRecordingBoxes(id: string): Promise<RecordingBoxes>;
  /** getRecordingVideo: the URL a <video> element can stream from, or null when no footage can be served. */
  recordingVideoUrl(recordingId: string): string | null;
  /** The URL an <img> can load for a server path such as a clip's snapshotUrl. */
  assetUrl(path: string): string;
  search(request: SearchRequest): Promise<SearchResponse>;
  /** Search the recordings that lack a new object, once. 409 budget_exceeded and 503 indexing_not_configured are possible. */
  requestConcept(body: ConceptRequest): Promise<ConceptJob>;
  /** Where the pass for an object is, for polling. 404 when none was asked for. */
  getConcept(noun: string): Promise<ConceptJob>;
  getClip(id: string): Promise<Clip>;
  listZones(camera?: string): Promise<Zone[]>;
  createZone(zone: ZoneCreate): Promise<Zone>;
  replaceZone(id: string, zone: ZoneUpdate): Promise<Zone>;
  deleteZone(id: string): Promise<void>;
  listSavedClips(day?: IsoDay): Promise<SavedClip[]>;
  saveClip(body: SavedClipCreate): Promise<SavedClip>;
  updateSavedClip(id: string, body: SavedClipUpdate): Promise<SavedClip>;
  deleteSavedClip(id: string): Promise<void>;
}

export { ApiError, apiErrorFromResponse, errorMessage, NETWORK_ERROR_MESSAGE } from './errors';

/** The URL of a recording's video on a server at baseUrl. */
export function recordingVideoUrlFor(baseUrl: string, recordingId: string): string {
  return `${trimBase(baseUrl)}/api/recordings/${encodeURIComponent(recordingId)}/video`;
}

const TRAILING_SLASHES = /\/+$/;

function trimBase(baseUrl: string): string {
  return baseUrl.replace(TRAILING_SLASHES, '');
}

type Query = Record<string, string | undefined>;

interface RequestOptions {
  query?: Query;
  json?: unknown;
  form?: FormData;
}

/** The real client: plain fetch against the API. No key, no secret, no auth header. */
export class FetchApiClient implements ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(baseUrl: string, fetchImpl?: typeof fetch) {
    this.baseUrl = trimBase(baseUrl);
    this.fetchImpl = fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  }

  private async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    let url = `${this.baseUrl}${path}`;
    if (options.query) {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(options.query)) {
        if (value !== undefined) params.set(key, value);
      }
      const text = params.toString();
      if (text) url += `?${text}`;
    }
    const init: RequestInit = { method, headers: { Accept: 'application/json' } };
    if (options.json !== undefined) {
      init.headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
      init.body = JSON.stringify(options.json);
    } else if (options.form) {
      init.body = options.form;
    }

    let response: Response;
    try {
      response = await this.fetchImpl(url, init);
    } catch {
      throw new ApiError(0, 'network_error', NETWORK_ERROR_MESSAGE);
    }
    if (!response.ok) throw await apiErrorFromResponse(response);
    if (response.status === 204) return undefined as T;
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError(response.status, 'invalid_response', 'The server sent an answer that could not be read. Try again.');
    }
  }

  getStatus(): Promise<Status> {
    return this.request('GET', '/api/status');
  }

  checkDemoCode(code: string): Promise<DemoCodeAccepted> {
    return this.request('POST', '/api/auth/demo-code', { json: { code } });
  }

  listCameras(): Promise<Camera[]> {
    return this.request('GET', '/api/cameras');
  }

  getCamera(id: string): Promise<Camera> {
    return this.request('GET', `/api/cameras/${encodeURIComponent(id)}`);
  }

  addCamera(body: CameraCreate): Promise<Camera> {
    return this.request('POST', '/api/cameras', { json: body });
  }

  updateCamera(id: string, body: CameraUpdate): Promise<Camera> {
    return this.request('PATCH', `/api/cameras/${encodeURIComponent(id)}`, { json: body });
  }

  deleteCamera(id: string, options?: DeleteCameraOptions): Promise<void> {
    // Sent only when true: the contract's default is false.
    const query = options?.deleteRecordings === true ? { deleteRecordings: 'true' } : undefined;
    return this.request('DELETE', `/api/cameras/${encodeURIComponent(id)}`, { query });
  }

  listDays(camera?: string): Promise<DaySummary[]> {
    return this.request('GET', '/api/days', { query: { camera } });
  }

  listRecordings(day: IsoDay, camera?: string): Promise<Recording[]> {
    return this.request('GET', '/api/recordings', { query: { day, camera } });
  }

  addRecording(file: File, day: IsoDay, camera: string): Promise<RecordingAccepted> {
    const form = new FormData();
    form.append('file', file);
    form.append('day', day);
    form.append('camera', camera);
    return this.request('POST', '/api/recordings', { form });
  }

  getRecordingBoxes(id: string): Promise<RecordingBoxes> {
    return this.request('GET', `/api/recordings/${encodeURIComponent(id)}/boxes`);
  }

  recordingVideoUrl(recordingId: string): string {
    return recordingVideoUrlFor(this.baseUrl, recordingId);
  }

  assetUrl(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  search(request: SearchRequest): Promise<SearchResponse> {
    return this.request('POST', '/api/search', { json: request });
  }

  requestConcept(body: ConceptRequest): Promise<ConceptJob> {
    return this.request('POST', '/api/concepts', { json: body });
  }

  getConcept(noun: string): Promise<ConceptJob> {
    return this.request('GET', `/api/concepts/${encodeURIComponent(noun)}`);
  }

  getClip(id: string): Promise<Clip> {
    return this.request('GET', `/api/clips/${encodeURIComponent(id)}`);
  }

  listZones(camera?: string): Promise<Zone[]> {
    return this.request('GET', '/api/zones', { query: { camera } });
  }

  createZone(zone: ZoneCreate): Promise<Zone> {
    return this.request('POST', '/api/zones', { json: zone });
  }

  replaceZone(id: string, zone: ZoneUpdate): Promise<Zone> {
    return this.request('PUT', `/api/zones/${encodeURIComponent(id)}`, { json: zone });
  }

  deleteZone(id: string): Promise<void> {
    return this.request('DELETE', `/api/zones/${encodeURIComponent(id)}`);
  }

  listSavedClips(day?: IsoDay): Promise<SavedClip[]> {
    return this.request('GET', '/api/saved-clips', { query: { day } });
  }

  saveClip(body: SavedClipCreate): Promise<SavedClip> {
    return this.request('POST', '/api/saved-clips', { json: body });
  }

  updateSavedClip(id: string, body: SavedClipUpdate): Promise<SavedClip> {
    return this.request('PATCH', `/api/saved-clips/${encodeURIComponent(id)}`, { json: body });
  }

  deleteSavedClip(id: string): Promise<void> {
    return this.request('DELETE', `/api/saved-clips/${encodeURIComponent(id)}`);
  }
}

/**
 * The client for an explicit choice (see mode.ts): the real one for VITE_API_URL, the in-memory demo one
 * only for VITE_API_MODE=mock. An unconfigured choice throws: there is no silent fallback to fake data.
 */
export function createApiClient(choice: ApiChoice = resolveApiChoice(import.meta.env)): ApiClient {
  if (choice.kind === 'api') return new FetchApiClient(choice.baseUrl);
  if (choice.kind === 'mock') return new MockApiClient({ latencyMs: 250, withFootagelessRecordings: true });
  throw new Error(choice.reason);
}
