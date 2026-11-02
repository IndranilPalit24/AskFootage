// Fixes from the hostile review: keys are handled once, stale failure explanations are dropped, zones follow the
// still's own shape, the review rail only uses a search that contains the clip, and a few small guarantees.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import packageJson from '../../web/package.json';
import { MockApiClient } from '../../web/src/api/mockClient';
import { explainVideoFailure, VideoPlayer } from '../../web/src/features/player/VideoPlayer';
import { pictureBox } from '../../web/src/features/zones/geometry';
import { ZoneFrame } from '../../web/src/features/zones/ZoneFrame';
import { renderApp, waitForBoot } from './ui-test-utils';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function playerWithClock() {
  const view = render(<VideoPlayer src="http://x/v.mp4" label="Clip" lengthHint={100} />);
  const video = view.container.querySelector('video')!;
  let time = 20;
  Object.defineProperty(video, 'currentTime', { get: () => time, set: (value: number) => (time = value), configurable: true });
  Object.defineProperty(video, 'duration', { value: 100, configurable: true });
  const play = vi.fn(() => Promise.resolve());
  video.play = play;
  video.pause = vi.fn();
  return { video, play, time: () => time };
}

describe('keys are handled once', () => {
  it('a focused <video> keeps space and the arrows for its own controls', () => {
    const { video, play, time } = playerWithClock();
    for (const key of [' ', 'k', 'ArrowRight', 'ArrowLeft', 'j', 'l']) fireEvent.keyDown(video, { key });
    expect(play).not.toHaveBeenCalled();
    expect(time()).toBe(20);
  });

  it('the arrow keys on the range scrubber seek 5 s, not the slider step', () => {
    const { time } = playerWithClock();
    const slider = screen.getByRole('slider', { name: 'Seek' });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(time()).toBe(25);
    fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    expect(time()).toBe(20);
  });
});

describe('explaining a failed video', () => {
  it('passes an abort signal, reads only the headers and gives up quietly when cancelled', async () => {
    const cancel = vi.fn(() => Promise.resolve());
    const fetchMock = vi.fn(() => Promise.resolve({ status: 200, ok: true, body: { cancel } } as unknown as Response));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    expect(await explainVideoFailure('http://x/v', controller.signal)).toContain('could not play it');
    expect(cancel).toHaveBeenCalledTimes(1); // a server that ignored Range: the body is not downloaded
    const [, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(options.signal).toBe(controller.signal);

    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new DOMException('aborted', 'AbortError'))));
    controller.abort();
    expect(await explainVideoFailure('http://x/v', controller.signal)).toBeNull();
  });

  it('a Try again aborts the earlier explanation, whose late answer is ignored', async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, options: RequestInit) => {
        signal = options.signal ?? undefined;
        return new Promise<Response>((_resolve, reject) => {
          options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        });
      }),
    );
    const { container } = render(<VideoPlayer src="http://x/v.mp4" label="Clip" />);
    fireEvent.error(container.querySelector('video')!);
    expect(screen.getByText('Checking why the video did not load…')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(signal?.aborted).toBe(true);
    expect(container.querySelector('video')).not.toBeNull();
    expect(screen.queryByText(/could not be reached/)).toBeNull();
  });

  it('aborts when the player goes away', () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => {
      signal = options.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    }));
    const { container, unmount } = render(<VideoPlayer src="http://x/v.mp4" label="Clip" />);
    fireEvent.error(container.querySelector('video')!);
    unmount();
    expect(signal?.aborted).toBe(true);
  });
});

describe('scrubber markers', () => {
  it('two markers at the same second do not collide', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(<VideoPlayer src="http://x/v.mp4" label="Clip" markers={[2, 2, 4]} lengthHint={10} />);
    expect(document.querySelectorAll('.scrubber__marker')).toHaveLength(3);
    expect(error).not.toHaveBeenCalled();
  });
});

describe('zones follow the picture, not the frame', () => {
  it('works out the picture box inside the 16:9 frame', () => {
    expect(pictureBox(null)).toEqual({ left: 0, top: 0, width: 1, height: 1 });
    expect(pictureBox(16 / 9)).toEqual({ left: 0, top: 0, width: 1, height: 1 });
    const four3 = pictureBox(4 / 3);
    expect(four3.width).toBeCloseTo(0.75);
    expect(four3.left).toBeCloseTo(0.125);
    expect(four3.height).toBe(1);
    const wide = pictureBox(21 / 9);
    expect(wide.width).toBe(1);
    expect(wide.top).toBeCloseTo((1 - 16 / 9 / (21 / 9)) / 2);
  });

  it('places the overlay on a 4:3 still once it has loaded', () => {
    const { container } = render(
      <ZoneFrame zones={[]} caption="Cam" drawing={false} draft={[]} onAddPoint={() => undefined} instructionsId="i" imageUrl="http://x/s.jpg" />,
    );
    const picture = container.querySelector<HTMLElement>('.frame__picture')!;
    expect(picture.style.left).toBe('0%');
    const image = container.querySelector('img')!;
    Object.defineProperty(image, 'naturalWidth', { value: 640 });
    Object.defineProperty(image, 'naturalHeight', { value: 480 });
    fireEvent.load(image);
    expect(picture.style.left).toBe('12.5%');
    expect(picture.style.width).toBe('75%');
  });
});

describe('the review rail only uses a search that contains the clip', () => {
  it('shows no measurements or other matches for a clip the search did not return', async () => {
    const client = new MockApiClient();
    const search = client.search.bind(client);
    const getClip = client.getClip.bind(client);
    vi.spyOn(client, 'search').mockImplementation(async (request) => {
      const response = await search(request);
      const first = response.clips[0];
      return {
        ...response,
        clips: [{ ...first, id: 'x' }, { ...first, id: 'z', label: 'Third match' }],
        proofs: [{ clipId: 'y', relation: 'carrying', startFrame: 1, endFrame: 2, startSeconds: 1.2, endSeconds: 4.8, trackIds: [0, 0], trackLabels: [], measures: [{ name: 'frames_together', value: 18 }], boxes: [] }],
      };
    });
    // Opening x shows a clip with another id, so the viewed clip (y) is not among the search's results.
    vi.spyOn(client, 'getClip').mockImplementation(async () => ({ ...(await getClip('clip-1029-104215')), id: 'y' }));
    renderApp('/', client);
    await waitForBoot();
    fireEvent.change(await screen.findByLabelText('Ask about the footage'), { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const cards = await screen.findAllByRole('article');
    fireEvent.click(within(cards[0]).getByRole('link', { name: 'Open' }));
    const rail = await screen.findByRole('complementary', { name: 'Evidence' });
    expect(rail.querySelector('[aria-label="Measurements"]')).toBeNull();
    expect(within(rail).queryByText('Other matches')).toBeNull();
  });
});

describe('sign-in Privacy link and dependencies', () => {
  it('Privacy is an in-app link that lands on the welcome page and scrolls to its section', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderApp('/sign-in');
    const link = screen.getByRole('link', { name: 'Privacy' });
    expect(link.getAttribute('href')).toBe('/welcome#privacy');
    fireEvent.click(link);
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(scroll.mock.contexts[0]).toBe(document.getElementById('privacy'));
    expect(screen.queryByText('Sign in to AskFootage')).toBeNull();
  });

  it('the web app carries no browser-automation dependency', () => {
    const all = { ...packageJson.dependencies, ...packageJson.devDependencies } as Record<string, string>;
    expect(Object.keys(all).filter((name) => /playwright|puppeteer/.test(name))).toEqual([]);
  });
});
