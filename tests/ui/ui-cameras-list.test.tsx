// The read-only Cameras list. Adding, editing and deleting cameras is deferred, so none of that is here.
import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Camera } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { deferred, renderApp } from './ui-test-utils';

/** The cells of each body row: name, status, location. */
function rowTexts(): string[][] {
  const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
  return rows.map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent ?? ''));
}

describe('Cameras list', () => {
  it('lists every camera in id order with its name, status and location', async () => {
    renderApp('/cameras');
    expect(screen.getByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
    await screen.findByRole('link', { name: 'Loading dock' });
    const headers = within(screen.getByRole('table')).getAllByRole('columnheader');
    expect(headers.map((header) => header.textContent)).toEqual(['Name', 'Status', 'Location']);
    expect(rowTexts()).toEqual([
      ['Loading dock', 'Online', 'Warehouse, north side'],
      ['Front gate', 'Standby', 'Main entrance'],
      ['Back door', 'Offline', 'Not set'],
    ]);
    expect(screen.getByText('Online').className).toBe('status status--ready');
    expect(screen.getByText('Offline').className).toBe('status');
  });

  it('links each camera to its recordings', async () => {
    renderApp('/cameras');
    await screen.findByRole('link', { name: 'Loading dock' });
    const hrefs = within(screen.getByRole('table'))
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'));
    expect(hrefs).toEqual(['/cameras/CAM-001/recordings', '/cameras/CAM-002/recordings', '/cameras/CAM-003/recordings']);

    fireEvent.click(screen.getByRole('link', { name: 'Front gate' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Recordings' })).toBeTruthy();
    expect(screen.getByText("Front gate · each day's recordings")).toBeTruthy();
  });

  it('is read-only and shows no stream address or credentials', async () => {
    renderApp('/cameras');
    await screen.findByRole('link', { name: 'Loading dock' });
    expect(screen.queryAllByRole('button', { name: /add|edit|delete|remove/i })).toEqual([]);
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(document.body.textContent).not.toMatch(/rtsp|192\.168|password|username/i);
  });

  it('says it is loading until the cameras arrive', async () => {
    const client = new MockApiClient();
    const held = deferred<Camera[]>();
    const realList = client.listCameras.bind(client);
    client.listCameras = () => held.promise;
    renderApp('/cameras', client);
    expect(await screen.findByText('Loading cameras…')).toBeTruthy();
    held.resolve(await realList());
    expect(await screen.findByRole('link', { name: 'Loading dock' })).toBeTruthy();
    expect(screen.queryByText('Loading cameras…')).toBeNull();
  });

  it('says so calmly when there are no cameras', async () => {
    const client = new MockApiClient();
    client.listCameras = async () => [];
    renderApp('/cameras', client);
    expect(await screen.findByText('No cameras yet.')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('sends the old /camera address to the list', async () => {
    renderApp('/camera');
    expect(await screen.findByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
  });

  it('says "Camera not found." for an unknown camera, with a way back', async () => {
    renderApp('/cameras/CAM-999/recordings');
    expect(await screen.findByRole('heading', { level: 1, name: 'Camera not found.' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'All cameras' }).getAttribute('href')).toBe('/cameras');
  });
});
