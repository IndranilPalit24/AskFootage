// The review-tool redesign: poster frames, the clip workspace (scrubber, shortcuts, evidence rail), skeleton and
// empty states, the busy ask box and per-screen page titles. All against the in-memory demo client.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MockApiClient } from '../../web/src/api/mockClient';
import type { SearchResponse } from '../../web/src/api/generated/types';
import { ClipThumb, clipPosterPath } from '../../web/src/components/ClipThumb';
import { EmptyState } from '../../web/src/components/EmptyState';
import { VideoPlayer } from '../../web/src/features/player/VideoPlayer';
import { formatDuration } from '../../web/src/lib/time';
import { deferred, renderApp, waitForBoot } from './ui-test-utils';

afterEach(() => vi.restoreAllMocks());

describe('poster frames', () => {
  it('prefers the poster, then the thumbnail, then the snapshot, else nothing', () => {
    expect(clipPosterPath({ posterUrl: '/p', thumbnailUrl: '/t', snapshotUrl: '/s' })).toBe('/p');
    expect(clipPosterPath({ posterUrl: null, thumbnailUrl: '/t', snapshotUrl: '/s' })).toBe('/t');
    expect(clipPosterPath({ posterUrl: null, thumbnailUrl: null, snapshotUrl: '/s' })).toBe('/s');
    expect(clipPosterPath({ posterUrl: null, thumbnailUrl: null, snapshotUrl: null })).toBeNull();
  });

  it('shows the still with its length chip, and a labelled neutral tile when there is none or it fails', () => {
    const { container, rerender } = render(<ClipThumb url="http://x/p.jpg" duration="0:04" />);
    const image = container.querySelector('img')!;
    expect(image.getAttribute('src')).toBe('http://x/p.jpg');
    expect(container.querySelector('.thumb__duration')?.textContent).toBe('Length 0:04');
    fireEvent.error(image);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('Preview unavailable')).toBeTruthy();
    rerender(<ClipThumb url={null} />);
    expect(screen.getByText('No preview')).toBeTruthy();
  });

  it('a result card loads the clip poster through the client and shows its length', async () => {
    const client = new MockApiClient();
    const search = client.search.bind(client);
    vi.spyOn(client, 'search').mockImplementation(async (request) => {
      const response: SearchResponse = await search(request);
      return { ...response, clips: response.clips.map((clip) => ({ ...clip, posterUrl: '/api/recordings/r/poster?t=3' })) };
    });
    vi.spyOn(client, 'assetUrl').mockImplementation((path) => `http://localhost:8000${path}`);
    renderApp('/', client);
    await waitForBoot();
    fireEvent.change(await screen.findByLabelText('Ask about the footage'), { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const card = (await screen.findAllByRole('article'))[0];
    expect(card.querySelector('img')?.getAttribute('src')).toBe('http://localhost:8000/api/recordings/r/poster?t=3');
    expect(card.querySelector('.thumb__duration')).not.toBeNull();
    expect(card.querySelector('.clip-card__reason')?.textContent?.length).toBeGreaterThan(10);
  });
});

describe('the video player: scrubber and keyboard shortcuts', () => {
  function setup() {
    const view = render(
      <VideoPlayer src="http://x/v.mp4" label="Clip" matchStart={2} matchEnd={6} markers={[2, 4, 6]} lengthHint={10} />,
    );
    const video = view.container.querySelector('video')!;
    let time = 20;
    Object.defineProperty(video, 'currentTime', { get: () => time, set: (value: number) => (time = value), configurable: true });
    Object.defineProperty(video, 'duration', { value: 100, configurable: true });
    const play = vi.fn(() => Promise.resolve());
    const pause = vi.fn();
    video.play = play;
    video.pause = pause;
    const stage = screen.getByRole('group', { name: 'Player: Clip' });
    return { video, stage, play, pause, time: () => time };
  }

  it('highlights the matched interval and marks the key moments, in a length taken from the hint', () => {
    render(<VideoPlayer src="http://x/v.mp4" label="Clip" matchStart={2} matchEnd={6} markers={[2, 4, 6]} lengthHint={10} />);
    const match = screen.getByTestId('scrubber-match');
    expect(match.style.left).toBe('20%');
    expect(match.style.width).toBe('40%');
    expect(document.querySelectorAll('.scrubber__marker')).toHaveLength(3);
    expect(screen.getByText('Matched interval', { exact: false }).textContent).toContain('0:02–0:06');
  });

  it('space and K play or pause; arrows jump 5 s; J and L jump 10 s', () => {
    const { stage, video, play, pause, time } = setup();
    fireEvent.keyDown(stage, { key: ' ' });
    expect(play).toHaveBeenCalledTimes(1);
    Object.defineProperty(video, 'paused', { value: false, configurable: true });
    fireEvent.keyDown(stage, { key: 'k' });
    expect(pause).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(stage, { key: 'ArrowRight' });
    expect(time()).toBe(25);
    fireEvent.keyDown(stage, { key: 'ArrowLeft' });
    expect(time()).toBe(20);
    fireEvent.keyDown(stage, { key: 'l' });
    expect(time()).toBe(30);
    fireEvent.keyDown(stage, { key: 'J' });
    expect(time()).toBe(20);
  });

  it('leaves the keys to the button that has focus, and shows a hint', () => {
    const { video, play } = setup();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Full screen' }), { key: ' ' });
    expect(play).not.toHaveBeenCalled();
    expect(video.currentTime).toBe(20);
    expect(screen.getByText('play / pause', { exact: false })).toBeTruthy();
  });

  it('the seek slider moves the video, and the play button toggles it', () => {
    const { video, play } = setup();
    fireEvent.change(screen.getByRole('slider', { name: 'Seek' }), { target: { value: '7.5' } });
    expect(video.currentTime).toBe(7.5);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(play).toHaveBeenCalled();
  });

  it('formats positions in minutes and seconds', () => {
    expect([formatDuration(4), formatDuration(75), formatDuration(3725), formatDuration(Number.NaN)]).toEqual(['0:04', '1:15', '1:02:05', '0:00']);
  });
});

describe('the clip workspace', () => {
  it('has the evidence rail with one primary action, and names the tab after the clip', async () => {
    renderApp('/clip/clip-1029-104215');
    await screen.findByRole('heading', { level: 1, name: 'Person carrying a box through the loading dock' });
    const rail = screen.getByRole('complementary', { name: 'Evidence' });
    expect(within(rail).getByRole('button', { name: 'Save clip' }).className).toContain('btn--primary');
    const panel = within(rail).getByRole('region', { name: 'Why this matched' });
    for (const term of ['Relation', 'Time range', 'Length', 'Camera', 'Day']) expect(within(panel).getByText(term)).toBeTruthy();
    expect(document.title).toBe('Person carrying a box through the loading dock · AskFootage');
  });

  it('shows skeleton shapes, not a spinner, while the clip loads', () => {
    const held = deferred<never>();
    const client = new MockApiClient();
    vi.spyOn(client, 'getClip').mockReturnValue(held.promise);
    renderApp('/clip/anything', client);
    expect(document.querySelector('.skeleton--stage')).not.toBeNull();
    expect(screen.getByRole('status').textContent).toBe('Loading clip…');
  });
});

describe('states and titles', () => {
  it('EmptyState shows a title, a sentence and one action; an error one is announced', () => {
    render(<EmptyState tone="error" title="Could not load" action={<button type="button">Try again</button>}>It broke.</EmptyState>);
    expect(screen.getByRole('alert').textContent).toContain('It broke.');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('gives each screen its own tab title', async () => {
    const { unmount } = renderApp('/cameras');
    await waitFor(() => expect(document.title).toBe('Cameras · AskFootage'));
    unmount();
    renderApp('/zones');
    await waitFor(() => expect(document.title).toBe('Zones · AskFootage'));
    document.body.innerHTML = '';
    renderApp('/nowhere');
    await waitFor(() => expect(document.title).toBe('Page not found · AskFootage'));
  });

  it('the 404 offers one primary way back', () => {
    renderApp('/nowhere');
    expect(screen.getByRole('link', { name: 'Go to Find Footage' }).className).toContain('btn--primary');
  });

  it('the saved list shows an empty state with an action', async () => {
    renderApp('/saved');
    expect(await screen.findByText('No saved clips yet. Use Save clip on any result to keep it here.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Find footage' }).getAttribute('href')).toBe('/');
  });

  it('shows a busy ask box and result skeletons while a search runs, and sends one search only', async () => {
    const held = deferred<SearchResponse>();
    const client = new MockApiClient();
    const search = vi.spyOn(client, 'search').mockReturnValue(held.promise);
    renderApp('/', client);
    await waitForBoot();
    const box = await screen.findByLabelText('Ask about the footage');
    fireEvent.change(box, { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(screen.getByTestId('ask-box').getAttribute('aria-busy')).toBe('true');
    expect(document.querySelector('.ask__progress')).not.toBeNull();
    expect(screen.getByText('Searching…')).toBeTruthy();
    expect(document.querySelectorAll('.clip-list .skeleton--poster').length).toBeGreaterThan(0);
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(search).toHaveBeenCalledTimes(1);
    await act(async () => held.resolve({ question: 'x', day: '2026-10-30', clips: [], note: null, proofs: [], needsIndexing: [] }));
    await waitFor(() => expect(screen.getByTestId('ask-box').getAttribute('aria-busy')).toBeNull());
  });
});
