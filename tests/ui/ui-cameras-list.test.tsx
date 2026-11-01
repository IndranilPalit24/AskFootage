// The camera registry list and the routes around it. Adding, status changes and deleting are in ui-cameras-page.test.tsx.
import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Camera } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { deferred, renderApp } from './ui-test-utils';

describe('Cameras list', () => {
  it('lists every camera in id order with its name, status and location', async () => {
    renderApp('/cameras');
    expect(screen.getByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
    await screen.findByRole('table');
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    const texts = rows.map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent ?? ''));
    expect(texts.map((cells) => [cells[1], cells[2], cells[5]?.startsWith('Online') ? 'Online' : cells[5]?.slice(0, 7)])).toEqual([
      ['Loading dock', 'Warehouse, north side', 'Online'],
      ['Front gate', 'Main entrance', 'Standby'],
      ['Back door', 'Not set', 'Offline'],
    ]);
  });

  it('links each online or standby camera to its recordings', async () => {
    renderApp('/cameras');
    await screen.findByRole('table');
    const hrefs = within(screen.getByRole('table'))
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'));
    expect(hrefs).toEqual(['/cameras/CAM-001/recordings', '/cameras/CAM-002/recordings']);

    fireEvent.click(within(screen.getByRole('table')).getAllByRole('link', { name: 'Recordings' })[1]);
    expect(await screen.findByRole('heading', { level: 1, name: 'Recordings' })).toBeTruthy();
    expect(screen.getByText("Front gate · each day's recordings")).toBeTruthy();
  });

  it('shows no stream address or credentials in the registry', async () => {
    renderApp('/cameras');
    await screen.findByRole('table');
    expect(screen.getByRole('table').textContent).not.toMatch(/rtsp|192.168|password|username/i);
  });

  it('says it is loading until the cameras arrive', async () => {
    const client = new MockApiClient();
    const held = deferred<Camera[]>();
    const realList = client.listCameras.bind(client);
    client.listCameras = () => held.promise;
    renderApp('/cameras', client);
    expect(await screen.findByText('Loading cameras…')).toBeTruthy();
    held.resolve(await realList());
    expect(await screen.findByRole('table')).toBeTruthy();
    expect(screen.queryByText('Loading cameras…')).toBeNull();
  });

  it('says so calmly when there are no cameras', async () => {
    const client = new MockApiClient();
    client.listCameras = async () => [];
    renderApp('/cameras', client);
    expect(await screen.findByText('No cameras yet. Add one in the Add new camera tab.')).toBeTruthy();
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
