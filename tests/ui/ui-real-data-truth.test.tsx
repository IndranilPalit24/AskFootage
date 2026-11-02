// Truthful to real data: no silent mock, a camera filter that keeps the question, visible failure reasons for
// media, measurements and other matches only from the server's answer, and the upload limitation stated.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MockApiClient } from '../../web/src/api/mockClient';
import { App } from '../../web/src/app/App';
import { ConfigErrorScreen } from '../../web/src/app/ConfigErrorScreen';
import { explainVideoFailure, VideoPlayer } from '../../web/src/features/player/VideoPlayer';
import { MemoryRouter } from 'react-router-dom';
import { renderApp, waitForBoot } from './ui-test-utils';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('API configuration is explicit', () => {
  it('says what is missing and how to start, instead of showing fake data', () => {
    render(<ConfigErrorScreen reason="VITE_API_URL is not set." />);
    expect(screen.getByRole('alert').textContent).toContain('VITE_API_URL is not set.');
    expect(screen.getByRole('alert').textContent).toContain('scripts.run_demo');
    expect(screen.getByRole('alert').textContent).toContain('VITE_API_MODE=mock');
    expect(document.title).toBe('API not configured · AskFootage');
  });

  it('mock mode shows a chip that real mode does not', async () => {
    const { unmount } = render(
      <MemoryRouter>
        <App client={new MockApiClient()} mock />
      </MemoryRouter>,
    );
    expect((await screen.findByRole('status', { name: '' })).textContent).toBe('Mock data: no real footage');
    unmount();
    renderApp('/');
    await waitForBoot();
    expect(screen.queryByText('Mock data: no real footage')).toBeNull();
  });
});

describe('a video that does not load says why', () => {
  const src = 'http://localhost:8000/api/recordings/x/video';

  it.each([
    [404, 'no video file'],
    [500, 'could not read the video'],
    [403, 'refused'],
    [206, 'could not play it'],
  ])('answer %i', async (status, phrase) => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status }))));
    expect(await explainVideoFailure(src)).toContain(phrase);
  });

  it('an unreachable API is named as such', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('failed'))));
    expect(await explainVideoFailure(src)).toContain('could not be reached');
  });

  it('shows the reason and a Try again that loads the video again', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))));
    const { container } = render(<VideoPlayer src={src} label="Clip" />);
    fireEvent.error(container.querySelector('video')!);
    expect(await screen.findByText(/no video file for this recording \(404\)/)).toBeTruthy();
    expect(container.querySelector('video')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(container.querySelector('video')?.getAttribute('src')).toBe(src);
  });
});

describe('Find Footage scope', () => {
  async function openFind(client = new MockApiClient()) {
    renderApp('/', client);
    await waitForBoot();
    return screen.findByLabelText<HTMLTextAreaElement>('Ask about the footage');
  }

  it('lists the real cameras, searches one when picked, and keeps the question when the filter changes', async () => {
    const client = new MockApiClient();
    const search = vi.spyOn(client, 'search');
    const box = await openFind(client);
    const select = screen.getByLabelText<HTMLSelectElement>('Camera:');
    const names = (await client.listCameras()).map((camera) => camera.name);
    expect([...select.options].slice(1).map((option) => option.textContent)).toEqual(
      (await client.listCameras()).map((camera) => `${camera.id} - ${camera.name}`),
    );
    expect(select.options[0].textContent).toBe('All cameras');

    fireEvent.change(box, { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText('Searched all ' + names.length + ' cameras on Fri 30 Oct');
    expect(search).toHaveBeenLastCalledWith({ question: 'someone carrying a box', day: '2026-10-30' });

    fireEvent.change(select, { target: { value: 'CAM-001' } });
    await waitFor(() => expect(search).toHaveBeenLastCalledWith({ question: 'someone carrying a box', day: '2026-10-30', camera: 'CAM-001' }));
    expect(await screen.findByText(`Searched ${names[0]} on Fri 30 Oct`)).toBeTruthy();
    expect(screen.getByLabelText<HTMLTextAreaElement>('Ask about the footage').value).toBe('someone carrying a box');
  });
});

describe('the review workspace uses only what the server sent', () => {
  it('shows the measurements and the other matches of the last search, and a way to the full recording', async () => {
    const client = new MockApiClient();
    const search = client.search.bind(client);
    vi.spyOn(client, 'search').mockImplementation(async (request) => {
      const response = await search(request);
      const first = response.clips[0];
      return {
        ...response,
        clips: [first, { ...first, id: 'other-match', label: 'Second match' }],
        proofs: [
          {
            clipId: first.id,
            relation: 'carrying',
            startFrame: 6,
            endFrame: 23,
            startSeconds: 1.2,
            endSeconds: 4.8,
            trackIds: [0, 0],
            trackLabels: ['person', 'box'],
            measures: [{ name: 'frames_together', value: 18 }],
            boxes: [],
          },
        ],
      };
    });
    renderApp('/', client);
    await waitForBoot();
    fireEvent.change(await screen.findByLabelText('Ask about the footage'), { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const cards = await screen.findAllByRole('article');
    fireEvent.click(within(cards[0]).getByRole('link', { name: /^Open( clip)?$/ }));
    const rail = await screen.findByRole('complementary', { name: 'Evidence' });
    const measurements = rail.querySelector<HTMLElement>('[aria-label="Measurements"]')!;
    expect(within(measurements).getByText('Frames together')).toBeTruthy();
    expect(within(measurements).getByText('18')).toBeTruthy();
    expect(within(rail).getByText('1.2 s to 4.8 s')).toBeTruthy();
    expect(within(rail).getByRole('link', { name: /Second match/ }).getAttribute('href')).toBe('/clip/other-match');
    expect(within(rail).getByRole('link', { name: 'Open full recording' }).getAttribute('href')).toMatch(/^\/recordings\//);
  });

  it('shows no measurements and no other matches when the clip is opened without a search', async () => {
    renderApp('/clip/clip-1029-104215');
    const rail = await screen.findByRole('complementary', { name: 'Evidence' });
    expect(rail.querySelector('[aria-label="Measurements"]')).toBeNull();
    expect(within(rail).queryByText('Other matches')).toBeNull();
  });
});

describe('upload limitation', () => {
  it('says a new recording is not stored or searchable until the server says Ready', async () => {
    renderApp('/cameras/CAM-001/recordings');
    expect((await screen.findByText(/only registers a recording/)).textContent).toMatch(/not stored or processed.*Ready/s);
  });
});
