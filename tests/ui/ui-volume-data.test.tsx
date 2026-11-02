// The generated demo dataset at volume: recordings without footage, long lists, and the permanent disclosure.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Recording } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { App } from '../../web/src/app/App';
import { ConfigErrorScreen } from '../../web/src/app/ConfigErrorScreen';
import { DemoDisclosure, DISCLOSURE } from '../../web/src/components/DemoDisclosure';
import { FOOTAGE_NOT_INCLUDED_NOTE } from '../../web/src/features/indexing/RecordingsTable';
import { VideoPlayer } from '../../web/src/features/player/VideoPlayer';
import { renderApp, waitForBoot } from './ui-test-utils';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function recordings(count: number, extra: Partial<Recording> = {}): Recording[] {
  return Array.from({ length: count }, (_, n) => ({
    id: `rec-${n}`,
    camera: 'CAM-001',
    day: '2026-10-30',
    startTime: `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}:00`,
    lengthSeconds: 600,
    status: 'ready' as const,
    posterUrl: null,
    hasFootage: false,
    ...extra,
  }));
}

function clientWith(list: Recording[]): MockApiClient {
  const client = new MockApiClient();
  vi.spyOn(client, 'listRecordings').mockResolvedValue(list);
  return client;
}

describe('a recording without footage', () => {
  it('shows its row as usual, with a quiet note instead of Open, no link and no picture', async () => {
    const list = [...recordings(2), { ...recordings(1)[0], id: 'with', startTime: '09:00:00', hasFootage: true, posterUrl: '/api/recordings/with/poster' }];
    renderApp('/cameras/CAM-001/recordings', clientWith(list));
    await screen.findAllByText(FOOTAGE_NOT_INCLUDED_NOTE);
    expect(screen.getAllByText('Footage not included in this demo build')).toHaveLength(2);
    expect(screen.getAllByRole('link', { name: /^Open( clip)?$/ })).toHaveLength(1); // only the one with footage
    expect(screen.getAllByRole('link', { name: /Watch the recording/ })).toHaveLength(1);
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText('Ready')).toBeTruthy(); // the row is shown normally
    expect(rows[0].querySelector('img')).toBeNull(); // no poster is requested without footage
  });

  it('a recording that is not ready keeps its plain status note', async () => {
    renderApp('/cameras/CAM-001/recordings', clientWith(recordings(1, { status: 'waiting' })));
    expect(await screen.findByText('Not uploaded yet')).toBeTruthy();
    expect(screen.queryByText(FOOTAGE_NOT_INCLUDED_NOTE)).toBeNull();
  });

  it('the player area shows the note, never a blank player, and requests no video', () => {
    const { container } = render(<VideoPlayer src="http://x/v.mp4" label="Clip" unavailableNote="Footage not included in this demo build" />);
    expect(screen.getByText('Footage not included in this demo build')).toBeTruthy();
    expect(container.querySelector('video, img')).toBeNull();
  });

  it('clip detail shows the note in the player area when the recording has no footage', async () => {
    const client = new MockApiClient();
    const real = await client.listRecordings('2026-10-29', 'CAM-001');
    vi.spyOn(client, 'listRecordings').mockResolvedValue(real.map((item) => ({ ...item, hasFootage: false })));
    vi.spyOn(client, 'recordingVideoUrl').mockImplementation((id) => `http://localhost:8000/api/recordings/${id}/video`);
    renderApp('/clip/clip-1029-104215', client);
    expect(await screen.findByText('Footage not included in this demo build')).toBeTruthy();
    expect(document.querySelector('video')).toBeNull();
  });

  it('a direct recording address for one answers with the note, not a blank player or a retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ error: { code: 'footage_not_included', message: 'Footage is not included for this recording.' } }), { status: 404 })),
      ),
    );
    const client = new MockApiClient();
    vi.spyOn(client, 'recordingVideoUrl').mockReturnValue('http://localhost:8000/api/recordings/rec-x/video');
    renderApp('/recordings/rec-x', client);
    await waitFor(() => expect(document.querySelector('video')).not.toBeNull());
    fireEvent.error(document.querySelector('video')!);
    expect(await screen.findByText('Footage not included in this demo build')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(document.querySelector('video')).toBeNull();
  });
});

describe('long lists are paged', () => {
  it('pages 120 recordings fifty at a time with real buttons, and starts again on another day', async () => {
    const client = clientWith(recordings(120));
    renderApp('/cameras/CAM-001/recordings', client);
    await screen.findByText('Showing 1–50 of 120 recordings');
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(51); // header + 50
    const nav = screen.getByRole('navigation', { name: 'recordings pages' });
    expect(within(nav).getByRole('button', { name: 'Previous page' }).getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(within(nav).getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('Showing 51–100 of 120 recordings')).toBeTruthy();
    expect(screen.getByText('Page 2 of 3')).toBeTruthy();
    fireEvent.click(within(nav).getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('Showing 101–120 of 120 recordings')).toBeTruthy();
    expect(within(table).getAllByRole('row')).toHaveLength(21);
    expect(within(nav).getByRole('button', { name: 'Next page' }).getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(within(nav).getByRole('button', { name: 'Previous page' }));
    expect(screen.getByText('Page 2 of 3')).toBeTruthy();
    // Another day: a different list, so back to page 1.
    fireEvent.click(screen.getByRole('button', { name: 'Thu 29' }));
    await screen.findByText('Showing 1–50 of 120 recordings');
  });

  it('shows no pager for a day that fits on one page', async () => {
    renderApp('/cameras/CAM-001/recordings', clientWith(recordings(30)));
    await screen.findAllByText(FOOTAGE_NOT_INCLUDED_NOTE);
    expect(screen.queryByRole('navigation', { name: 'recordings pages' })).toBeNull();
  });

  it('the mock client can carry footage-less recordings, enough to page', async () => {
    const client = new MockApiClient({ withFootagelessRecordings: true });
    const list = await client.listRecordings('2026-10-30', 'CAM-001');
    expect(list.filter((item) => item.hasFootage === false).length).toBeGreaterThan(50);
    expect(list.some((item) => item.hasFootage)).toBe(true);
    // Off by default: the contract examples' counts stay as they are.
    expect((await new MockApiClient().listRecordings('2026-10-30', 'CAM-001')).every((item) => item.hasFootage)).toBe(true);
  });

  it('keeps the 18-camera registry on one tidy table with a Cameras filter that lists them all', async () => {
    const client = new MockApiClient();
    const base = (await client.listCameras())[0];
    const eighteen = Array.from({ length: 18 }, (_, n) => ({ ...base, id: `CAM-${String(n + 1).padStart(3, '0')}`, name: `Camera ${n + 1}` }));
    vi.spyOn(client, 'listCameras').mockResolvedValue(eighteen);
    renderApp('/', client);
    await waitForBoot();
    const select = await screen.findByLabelText<HTMLSelectElement>('Camera:');
    expect(select.options).toHaveLength(19);
  });
});

describe('the permanent disclosure', () => {
  const routes = ['/', '/cameras', '/cameras/CAM-001/recordings', '/zones', '/saved', '/clip/clip-1029-104215', '/recordings/clip1', '/nowhere', '/welcome', '/sign-in'];

  it.each(routes)('is on %s', async (route) => {
    renderApp(route);
    expect(await screen.findByText(DISCLOSURE)).toBeTruthy();
    expect(screen.getAllByText(DISCLOSURE)).toHaveLength(1);
  });

  it('is on the configuration error screen too', () => {
    render(<ConfigErrorScreen reason="VITE_API_URL is not set." />);
    expect(screen.getByText(DISCLOSURE)).toBeTruthy();
  });

  it('cannot be hidden: it takes no props and is the same sentence everywhere', () => {
    expect(DemoDisclosure.length).toBe(0);
    expect(DISCLOSURE).toBe('This build includes a generated demo dataset.');
    expect(DISCLOSURE).not.toMatch(/real|facility|factory|live/i);
  });

  it('no app screen carries a "sample" or "demo data" chip, badge or watermark', async () => {
    for (const route of ['/', '/cameras', '/cameras/CAM-001/recordings', '/zones', '/saved', '/clip/clip-1029-104215']) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[route]}>
          <App client={new MockApiClient()} />
        </MemoryRouter>,
      );
      await screen.findByText(DISCLOSURE);
      expect(screen.queryByText(/\bsample\b|demo data\b|watermark/i)).toBeNull();
      expect(document.querySelector('.chip--mock')).toBeNull();
      unmount();
    }
  });
});
