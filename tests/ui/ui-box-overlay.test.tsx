// The box overlay over the <video>, the player's full-screen button, and the screens that use them.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RecordingBoxes } from '../../web/src/api/generated/types';
import { ApiError } from '../../web/src/api/client';
import { MockApiClient } from '../../web/src/api/mockClient';
import { BoxOverlay } from '../../web/src/features/player/BoxLayer';
import { VideoPlayer } from '../../web/src/features/player/VideoPlayer';
import example from '../../contract/examples/recording-boxes.json';
import { giveSize, renderApp } from './ui-test-utils';

const clip2 = example as unknown as RecordingBoxes;
const personOnly: RecordingBoxes = { ...clip2, recordingId: 'clip1', tracks: [clip2.tracks[0]!] };

/** A <video> with a pretend size, picture size and clock (jsdom has none). */
function fakeVideo(width: number, height: number, picture = { width: 1920, height: 1080 }) {
  const video = document.createElement('video');
  giveSize(video, width, height);
  let time = 0;
  Object.defineProperty(video, 'currentTime', { get: () => time, set: (value: number) => (time = value), configurable: true });
  Object.defineProperty(video, 'videoWidth', { value: picture.width, configurable: true });
  Object.defineProperty(video, 'videoHeight', { value: picture.height, configurable: true });
  return video;
}

function seek(video: HTMLVideoElement, seconds: number) {
  video.currentTime = seconds;
  fireEvent(video, new Event('seeked'));
}

const style = (element: HTMLElement) => {
  const { left, top, width, height } = element.style;
  return { left, top, width, height };
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('BoxOverlay', () => {
  it('draws the object red box and the person box at the mapped pixels, with no pointer events', () => {
    const video = fakeVideo(960, 540);
    render(<BoxOverlay boxes={clip2} video={video} />);
    expect(screen.queryByTestId('box-overlay-object')).toBeNull(); // time 0: before the track

    act(() => seek(video, 1));
    expect(style(screen.getByTestId('box-overlay-object'))).toEqual({ left: '400px', top: '250px', width: '100px', height: '100px' });
    expect(style(screen.getByTestId('box-overlay-person'))).toEqual({ left: '350px', top: '100px', width: '200px', height: '400px' });
    expect(screen.getByTestId('box-overlay-object').className).toContain('box-overlay__box--object');
    expect(screen.getByRole('img', { name: 'cardboard box outlined on the video' })).toBe(screen.getByTestId('box-overlay-object'));
  });

  it('places the box inside the picture when the player is letterboxed', () => {
    const video = fakeVideo(960, 720);
    render(<BoxOverlay boxes={clip2} video={video} />);
    act(() => seek(video, 1));
    expect(style(screen.getByTestId('box-overlay-object'))).toEqual({ left: '400px', top: '340px', width: '100px', height: '100px' });
  });

  it('follows a resize of the player', () => {
    const video = fakeVideo(960, 540);
    render(<BoxOverlay boxes={clip2} video={video} />);
    act(() => seek(video, 1));
    giveSize(video, 1920, 1080);
    act(() => {
      fireEvent(video, new Event('resize'));
    });
    expect(style(screen.getByTestId('box-overlay-object'))).toEqual({ left: '800px', top: '500px', width: '200px', height: '200px' });
  });

  it('removes the boxes in a gap, before the track starts and after it ends', () => {
    const video = fakeVideo(960, 540);
    render(<BoxOverlay boxes={clip2} video={video} />);
    act(() => seek(video, 1));
    expect(screen.getAllByRole('img')).toHaveLength(2);
    act(() => seek(video, 3));
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    act(() => seek(video, 0.2));
    expect(screen.queryAllByRole('img')).toHaveLength(0);
  });

  it('draws nothing for a recording with only a person', () => {
    const video = fakeVideo(960, 540);
    render(<BoxOverlay boxes={personOnly} video={video} />);
    act(() => seek(video, 1));
    expect(screen.queryByTestId('box-overlay-person')).toBeNull();
    expect(screen.queryByTestId('box-overlay-object')).toBeNull();
  });

  it('follows the clock with animation frames while playing, and stops on pause and unmount', () => {
    const callbacks = new Map<number, FrameRequestCallback>();
    let next = 1;
    const request = vi.fn((callback: FrameRequestCallback) => {
      callbacks.set(next, callback);
      return next++;
    });
    const cancel = vi.fn((id: number) => void callbacks.delete(id));
    vi.stubGlobal('requestAnimationFrame', request);
    vi.stubGlobal('cancelAnimationFrame', cancel);
    const runFrame = () => {
      const pending = [...callbacks.entries()];
      callbacks.clear();
      act(() => pending.forEach(([, callback]) => callback(0)));
    };

    const video = fakeVideo(960, 540);
    const { unmount } = render(<BoxOverlay boxes={clip2} video={video} />);
    expect(request).not.toHaveBeenCalled(); // paused: no loop

    act(() => {
      fireEvent(video, new Event('play'));
    });
    expect(request).toHaveBeenCalledTimes(1);
    video.currentTime = 1; // the clock moves without any event
    runFrame();
    expect(screen.getByTestId('box-overlay-object')).toBeTruthy();
    video.currentTime = 3;
    runFrame();
    expect(screen.queryByTestId('box-overlay-object')).toBeNull();

    act(() => {
      fireEvent(video, new Event('pause'));
    });
    expect(callbacks.size).toBe(0);

    act(() => {
      fireEvent(video, new Event('play'));
    });
    expect(callbacks.size).toBe(1);
    unmount();
    expect(callbacks.size).toBe(0);
  });

  it('removes its listeners and observer on unmount', () => {
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe = observe;
        disconnect = disconnect;
        unobserve = vi.fn();
      },
    );
    const video = fakeVideo(960, 540);
    const removed = vi.spyOn(video, 'removeEventListener');
    const { unmount } = render(<BoxOverlay boxes={clip2} video={video} />);
    expect(observe).toHaveBeenCalledWith(video);
    unmount();
    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(removed.mock.calls.map((call) => call[0])).toEqual(expect.arrayContaining(['timeupdate', 'seeked', 'pause', 'play']));
    // A late event after unmount changes nothing and throws nothing.
    expect(() => seek(video, 1)).not.toThrow();
  });
});

describe('VideoPlayer', () => {
  it('layers the overlay inside the wrapper that goes full screen, and keeps the native full screen off', async () => {
    const { container } = render(<VideoPlayer src="http://localhost:8000/v.mp4" label="Test" boxes={clip2} />);
    const wrapper = container.querySelector<HTMLElement>('.player')!;
    const video = wrapper.querySelector('video')!;
    expect(video.getAttribute('controlslist')).toBe('nofullscreen');
    expect(wrapper.querySelector('[data-testid="box-overlay"]')).not.toBeNull();

    const requestFullscreen = vi.fn(() => Promise.resolve());
    wrapper.requestFullscreen = requestFullscreen;
    const button = screen.getByRole('button', { name: 'Full screen' });
    expect(button.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(button);
    expect(requestFullscreen).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, 'fullscreenElement', { value: wrapper, configurable: true });
    act(() => {
      fireEvent(document, new Event('fullscreenchange'));
    });
    expect(screen.getByRole('button', { name: 'Full screen' }).getAttribute('aria-pressed')).toBe('true');

    const exitFullscreen = vi.fn(() => Promise.resolve());
    document.exitFullscreen = exitFullscreen;
    fireEvent.click(screen.getByRole('button', { name: 'Full screen' }));
    expect(exitFullscreen).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true });
  });

  it('survives a refused full screen request', async () => {
    const { container } = render(<VideoPlayer src="http://localhost:8000/v.mp4" label="Test" />);
    container.querySelector<HTMLElement>('.player')!.requestFullscreen = () => Promise.reject(new Error('denied'));
    fireEvent.click(screen.getByRole('button', { name: 'Full screen' }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByRole('button', { name: 'Full screen' })).toBeTruthy();
    expect(container.querySelector('[data-testid="box-overlay"]')).toBeNull(); // no boxes given: no overlay
  });

  it('has no full screen button on the placeholder', () => {
    render(<VideoPlayer src={null} label="Test" />);
    expect(screen.queryByRole('button', { name: 'Full screen' })).toBeNull();
  });
});

/** The demo client, but with a video URL (as the real API gives), and optionally other boxes. */
function clientWith(boxes?: (id: string) => Promise<RecordingBoxes>): MockApiClient {
  const client = new MockApiClient();
  vi.spyOn(client, 'recordingVideoUrl').mockImplementation((id) => `http://localhost:8000/api/recordings/${id}/video`);
  if (boxes) vi.spyOn(client, 'getRecordingBoxes').mockImplementation(boxes);
  return client;
}

async function findVideo(): Promise<HTMLVideoElement> {
  await waitFor(() => expect(document.querySelector('video')).not.toBeNull());
  return document.querySelector('video')!;
}

/** Waits for the overlay layer (the boxes arrived), gives the video a size and moves its clock. */
async function playAt(seconds: number, size = { width: 960, height: 540 }) {
  const video = await findVideo();
  await screen.findByTestId('box-overlay');
  giveSize(video, size.width, size.height);
  act(() => seek(video, seconds));
  return video;
}

describe('Clip detail with boxes', () => {
  const CLIP = '/clip/clip-1029-104215';
  it('draws the stored boxes over the clip video, and still shows the evidence snapshot', async () => {
    renderApp(CLIP, clientWith());
    await screen.findByRole('heading', { level: 1, name: 'Person carrying a box through the loading dock' });
    const video = await playAt(1);
    expect(video.getAttribute('src')).toBe('http://localhost:8000/api/recordings/rec-1029-1030/video');
    expect(style(screen.getByTestId('box-overlay-object'))).toEqual({ left: '400px', top: '250px', width: '100px', height: '100px' });
    expect(screen.getByText('Box in red, person in grey')).toBeTruthy();
  });

  it('is silent when the boxes cannot be loaded (404)', async () => {
    renderApp(CLIP, clientWith(() => Promise.reject(new ApiError(404, 'not_found', 'Recording not found.'))));
    await screen.findByRole('heading', { level: 1, name: 'Person carrying a box through the loading dock' });
    const video = await findVideo();
    giveSize(video, 960, 540);
    act(() => seek(video, 1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId('box-overlay')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('is silent when the answer has no tracks', async () => {
    renderApp(CLIP, clientWith(async () => ({ ...clip2, tracks: [] })));
    await screen.findByRole('heading', { level: 1, name: 'Person carrying a box through the loading dock' });
    const video = await findVideo();
    giveSize(video, 960, 540);
    act(() => seek(video, 1));
    await screen.findByTestId('box-overlay');
    expect(screen.queryAllByRole('img', { name: /outlined on the video/ })).toHaveLength(0);
  });
});

describe('Recording player screen', () => {
  it('opens a recording with no clip data and draws the boxes over it', async () => {
    const client = clientWith();
    renderApp('/recordings/clip2', client);
    expect(await screen.findByRole('heading', { level: 1, name: 'Recording' })).toBeTruthy();
    const video = await playAt(1);
    expect(video.getAttribute('src')).toBe('http://localhost:8000/api/recordings/clip2/video');
    expect(style(screen.getByTestId('box-overlay-object'))).toEqual({ left: '400px', top: '250px', width: '100px', height: '100px' });
    expect(screen.getByTestId('box-overlay-person')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'All cameras' }).getAttribute('href')).toBe('/cameras');
  });

  it('shows no box at all for clip1, which has only a person', async () => {
    renderApp('/recordings/clip1', clientWith(async () => personOnly));
    const video = await playAt(1);
    expect(video).toBeTruthy();
    expect(screen.queryByTestId('box-overlay-person')).toBeNull();
    expect(screen.queryByTestId('box-overlay-object')).toBeNull();
  });

  it('shows the calm placeholder when the demo has no footage file', async () => {
    renderApp('/recordings/clip2');
    expect(await screen.findByText('Footage file not attached')).toBeTruthy();
    expect(document.querySelector('video')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('is silent when the recording is unknown to the server', async () => {
    renderApp('/recordings/nope', clientWith());
    const video = await findVideo();
    giveSize(video, 960, 540);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId('box-overlay')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('Cameras to recordings to the player', () => {
  it('a ready recording opens in the player from its start time', async () => {
    renderApp('/cameras/CAM-001/recordings', clientWith());
    const link = (await screen.findAllByRole('link', { name: /^Watch the recording from / }))[0]!;
    expect(link.getAttribute('href')).toMatch(/^\/recordings\/rec-/);
    expect(link.closest('tr')?.textContent).toContain('Open');
    fireEvent.click(link);
    expect(await screen.findByRole('heading', { level: 1, name: 'Recording' })).toBeTruthy();
    cleanup();
  });

  it('only ready recordings can be watched', async () => {
    renderApp('/cameras/CAM-001/recordings', clientWith());
    await screen.findAllByRole('link', { name: /^Watch the recording from / });
    const rows = screen.getAllByRole('row').slice(1);
    for (const row of rows) {
      const watchable = row.querySelector('a[aria-label^="Watch"]') !== null;
      expect(watchable).toBe(row.textContent?.includes('Ready'));
    }
  });
});

describe('Demo client boxes', () => {
  it('serves the example for clip2 and the demo clip, none for another known recording, 404 for an unknown one', async () => {
    const client = new MockApiClient();
    expect((await client.getRecordingBoxes('clip2')).tracks).toEqual(clip2.tracks);
    const demo = await client.getRecordingBoxes('rec-1029-1030');
    expect(demo.recordingId).toBe('rec-1029-1030');
    expect(demo.tracks).toHaveLength(2);
    expect((await client.getRecordingBoxes('rec-1029-0600')).tracks).toEqual([]);
    await expect(client.getRecordingBoxes('missing')).rejects.toMatchObject({ status: 404, code: 'not_found' });
  });
});
