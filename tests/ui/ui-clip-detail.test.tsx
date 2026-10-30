import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MockApiClient } from '../../web/src/api/mockClient';
import { renderApp } from './ui-test-utils';

const CLIP_PATH = '/clip/clip-1029-104215';
const TITLE = 'Person carrying a box through the loading dock';

async function openClip(client = new MockApiClient()) {
  const view = renderApp(CLIP_PATH, client);
  await screen.findByRole('heading', { level: 1, name: TITLE });
  return view;
}

/** The demo client, but with a video URL, as the real API gives one: the <video> element renders. */
function withVideo(): MockApiClient {
  const client = new MockApiClient();
  vi.spyOn(client, 'recordingVideoUrl').mockImplementation((id) => `http://localhost:8000/api/recordings/${id}/video`);
  return client;
}

describe('Clip detail', () => {
  it('shows the title, the day, time and camera, the back link and Save clip', async () => {
    await openClip();
    expect(screen.getByText('Thu 29 Oct · 10:42:15–10:42:31 · Loading dock')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Back to results' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('button', { name: 'Save clip' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('shows a calm placeholder when there is no footage file, never an error page', async () => {
    await openClip();
    expect(screen.getByText('Footage file not attached')).toBeTruthy();
    expect(screen.getByText('The evidence below is still available.')).toBeTruthy();
    expect(document.querySelector('video')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('swaps a video that fails to load (404) for the same placeholder', async () => {
    await openClip(withVideo());
    const video = document.querySelector('video')!;
    expect(video.getAttribute('src')).toBe('http://localhost:8000/api/recordings/rec-1029-1030/video');
    fireEvent.error(video);
    expect(screen.getByText('Footage file not attached')).toBeTruthy();
    expect(document.querySelector('video')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('region', { name: 'Why this matched' })).toBeTruthy();
  });

  it('explains why it matched: the reason, evidence chips, the zone and neutral object labels', async () => {
    await openClip();
    const panel = screen.getByRole('region', { name: 'Why this matched' });
    expect(within(panel).getByText(/A person was tracked holding a box for 16 seconds\./)).toBeTruthy();
    const chips = within(within(panel).getByRole('list', { name: 'Evidence' })).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['Carrying · 16 s', 'In Loading door · 11 s']);
    expect(within(panel).getByText('Zone:').parentElement?.textContent).toBe('Zone: Loading door');
    const objects = within(panel).getByRole('list', { name: 'Matched objects:' });
    expect(within(objects).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['person', 'box']);
  });

  it('draws the day timeline with the recordings and the matched moment highlighted', async () => {
    await openClip();
    const bar = screen.getByRole('img', { name: 'Matched at 10:42 on Thu 29 Oct' });
    await waitFor(() => expect(bar.querySelectorAll('.timeline__segment')).toHaveLength(6));
    // 10:42:15 is 38535 s after midnight: 44.601% of the day.
    expect(within(bar).getByTestId('timeline-match').style.left).toBe('44.601%');
    for (const tick of ['00:00', '06:00', '12:00', '18:00', '24:00']) expect(screen.getByText(tick)).toBeTruthy();
  });

  it('lists the key frames by wall-clock time and marks the chosen one', async () => {
    await openClip();
    const frames = within(screen.getByRole('list', { name: 'Key frames' })).getAllByRole('button');
    expect(frames.map((frame) => frame.textContent)).toEqual(['10:42:15', '10:42:23', '10:42:31']);
    expect(frames.every((frame) => frame.getAttribute('aria-pressed') === 'false')).toBe(true);
    fireEvent.click(frames[1]);
    expect(frames[1].getAttribute('aria-pressed')).toBe('true');
    expect(frames[0].getAttribute('aria-pressed')).toBe('false');
  });

  it('starts the player at the clip and jumps to a key frame when it is clicked', async () => {
    await openClip(withVideo());
    const video = document.querySelector('video')!;
    expect(video.hasAttribute('controls')).toBe(true);
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(735);
    // atSeconds counts from the start of the recording, which is what the video plays.
    fireEvent.click(screen.getByRole('button', { name: '10:42:31' }));
    expect(video.currentTime).toBe(751);
  });

  it('says "Clip not found." with a way back for an unknown id', async () => {
    renderApp('/clip/clip-does-not-exist');
    expect(await screen.findByRole('heading', { level: 1, name: 'Clip not found.' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Back to results' }).getAttribute('href')).toBe('/');
  });
});
