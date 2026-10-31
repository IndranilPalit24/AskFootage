import { ApiError, apiErrorFromResponse, NETWORK_ERROR_MESSAGE } from './errors';
import type {
  Camera,
  CameraCreate,
  CameraUpdate,
  Clip,
  DaySummary,
  IsoDay,
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
import { MockApiClient } from './mockClient';

/** One method per operation in contract/openapi.yaml. */
export interface ApiClient {
  getStatus(): Promise<Status>;
  /** In id order. */
  listCameras(): Promise<Camera[]>;
  getCamera(id: string): Promise<Camera>;
  /** 201 with the new camera; 409 camera_name_taken when the name is in use, ignoring case. */
  addCamera(body: CameraCreate): Promise<Camera>;
  updateCamera(id: string, body: CameraUpdate): Promise<Camera>;
  /** Also removes the camera's recordings, zones and saved clips. */
  deleteCamera(id: string): Promise<void>;
  /** Without camera: the counts cover all cameras. */
  listDays(camera?: string): Promise<DaySummary[]>;
  /** Without camera: every camera's recordings. */
  listRecordings(day: IsoDay, camera?: string): Promise<Recording[]>;
  addRecording(file: File, day: IsoDay, camera: string): Promise<RecordingAccepted>;
  /** getRecordingVideo: the URL a <video> element can stream from, or null when no footage can be served. */
  recordingVideoUrl(recordingId: string): string | null;
  search(request: SearchRequest): Promise<SearchResponse>;
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

  deleteCamera(id: string): Promise<void> {
    return this.request('DELETE', `/api/cameras/${encodeURIComponent(id)}`);
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

  recordingVideoUrl(recordingId: string): string {
    return recordingVideoUrlFor(this.baseUrl, recordingId);
  }

  search(request: SearchRequest): Promise<SearchResponse> {
    return this.request('POST', '/api/search', { json: request });
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
 * The real client when VITE_API_URL is set at build time (for example http://localhost:8000),
 * otherwise the in-memory demo client.
 */
export function createApiClient(): ApiClient {
  const baseUrl = import.meta.env.VITE_API_URL;
  if (baseUrl) return new FetchApiClient(baseUrl);
  return new MockApiClient({ latencyMs: 250 });
}
