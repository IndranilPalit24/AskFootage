import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Point } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { normalisedPoint, nudge } from '../../web/src/features/zones/geometry';
import { giveSize, renderApp } from './ui-test-utils';

async function openZones(client = new MockApiClient()) {
  const view = renderApp('/zones', client);
  const list = await screen.findByRole('list', { name: 'Zones' });
  return { ...view, list };
}

/** Starts a new zone on an 800 x 450 frame. */
function startDrawing(): HTMLElement {
  fireEvent.click(screen.getByRole('button', { name: 'New zone' }));
  const frame = screen.getByTestId('zone-frame');
  giveSize(frame, 800, 450);
  return frame;
}

function saveButton(): HTMLButtonElement {
  return screen.getByRole<HTMLButtonElement>('button', { name: 'Save zone' });
}

/** The contract's rule for Zone.points: at least 3 points, each [x, y] with both values in 0..1. */
function isValidPolygon(points: Point[]): boolean {
  return points.length >= 3 && points.every((point) => point.length === 2 && point.every((value) => value >= 0 && value <= 1));
}

describe('Zones screen', () => {
  it('shows the still frame with the existing zones drawn over it, in 0..1 coordinates', async () => {
    await openZones();
    const frame = screen.getByTestId('zone-frame');
    expect(frame.getAttribute('aria-label')).toBe('Loading dock · still frame with zones: Exit lane, Loading door');
    const svg = frame.querySelector('svg')!;
    expect(svg.getAttribute('viewBox')).toBe('0 0 1 1');
    expect(svg.getAttribute('preserveAspectRatio')).toBe('none');
    const polygons = svg.querySelectorAll('polygon');
    expect(polygons).toHaveLength(2);
    expect(polygons[1].getAttribute('points')).toBe('0.08,0.22 0.42,0.2 0.44,0.86 0.06,0.9');
  });

  it('click-to-place drawing sends a valid polygon to createZone, and the zone joins the list', async () => {
    const client = new MockApiClient();
    const create = vi.spyOn(client, 'createZone');
    const { list } = await openZones(client);
    const frame = startDrawing();

    expect(saveButton().disabled).toBe(true);
    fireEvent.click(frame, { clientX: 80, clientY: 45 });
    fireEvent.click(frame, { clientX: 400, clientY: 45 });
    fireEvent.click(frame, { clientX: 900, clientY: 300 }); // past the edge: clamped to 0..1
    expect(screen.getAllByTestId('draft-point')).toHaveLength(3);
    expect(frame.querySelector('polygon.frame__draft')).toBeTruthy();
    expect(saveButton().disabled).toBe(true); // three points, but no name yet

    fireEvent.click(frame, { clientX: 123, clientY: 400 });
    fireEvent.click(screen.getByRole('button', { name: 'Undo point' }));
    expect(screen.getAllByTestId('draft-point')).toHaveLength(3);
    fireEvent.click(frame, { clientX: 100, clientY: 333 });

    fireEvent.change(screen.getByLabelText('Zone name'), { target: { value: '  Forklift bay  ' } });
    expect(saveButton().disabled).toBe(false);
    fireEvent.click(saveButton());

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    const sent = create.mock.calls[0][0];
    expect(sent).toEqual({
      camera: 'loading-dock',
      name: 'Forklift bay',
      points: [
        [0.1, 0.1],
        [0.5, 0.1],
        [1, 0.6667],
        [0.125, 0.74],
      ],
    });
    expect(isValidPolygon(sent.points)).toBe(true);

    const row = (await within(list).findByText('Forklift bay')).closest('li')!;
    expect(within(row).getByText('4 points')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Save zone' })).toBeNull();
    expect(screen.getByTestId('zone-frame').querySelectorAll('polygon.frame__zone')).toHaveLength(3);
  });

  it('draws with the keyboard too: arrows move a cursor, Enter or Space places a point', async () => {
    const client = new MockApiClient();
    const { list } = await openZones(client);
    const frame = startDrawing();
    expect(frame.getAttribute('tabindex')).toBe('0');
    expect(frame.getAttribute('role')).toBe('application');
    fireEvent.keyDown(frame, { key: 'Enter' }); // the centre
    fireEvent.keyDown(frame, { key: 'ArrowRight', shiftKey: true });
    fireEvent.keyDown(frame, { key: 'Enter' });
    fireEvent.keyDown(frame, { key: 'ArrowDown', shiftKey: true });
    fireEvent.keyDown(frame, { key: ' ' });
    expect(screen.getAllByTestId('draft-point')).toHaveLength(3);
    expect(screen.getByText('3 points.')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Zone name'), { target: { value: 'Middle' } });
    fireEvent.click(saveButton());
    await within(list).findByText('Middle');
    const created = (await client.listZones('loading-dock')).find((zone) => zone.name === 'Middle');
    expect(created?.points).toEqual([
      [0.5, 0.5],
      [0.55, 0.5],
      [0.55, 0.55],
    ]);
  });

  it('Cancel leaves drawing mode without saving', async () => {
    const client = new MockApiClient();
    const create = vi.spyOn(client, 'createZone');
    await openZones(client);
    fireEvent.click(startDrawing(), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('draft-point')).toBeNull();
    expect(screen.getByRole('button', { name: 'New zone' })).toBeTruthy();
    expect(create).not.toHaveBeenCalled();
  });

  it('explains a name that is already taken and keeps the drawing', async () => {
    await openZones();
    const frame = startDrawing();
    fireEvent.click(frame, { clientX: 10, clientY: 10 });
    fireEvent.click(frame, { clientX: 200, clientY: 10 });
    fireEvent.click(frame, { clientX: 200, clientY: 200 });
    fireEvent.change(screen.getByLabelText('Zone name'), { target: { value: 'loading door' } });
    fireEvent.click(saveButton());
    expect((await screen.findByRole('alert')).textContent).toBe('A zone called loading door already exists on this camera.');
    expect(screen.getAllByTestId('draft-point')).toHaveLength(3);
  });

  it('renames a zone inline (PUT with the same points) and reports a taken name', async () => {
    const client = new MockApiClient();
    const replace = vi.spyOn(client, 'replaceZone');
    const { list } = await openZones(client);
    fireEvent.click(within(list).getByRole('button', { name: 'Rename Loading door' }));
    const field = within(list).getByLabelText('New name for Loading door');

    fireEvent.change(field, { target: { value: 'Exit lane' } });
    fireEvent.click(within(list).getByRole('button', { name: 'Save' }));
    expect(await within(list).findByText('A zone called Exit lane already exists on this camera.')).toBeTruthy();

    fireEvent.change(field, { target: { value: 'Dock door' } });
    fireEvent.click(within(list).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(within(list).getByText('Dock door')).toBeTruthy());
    expect(replace).toHaveBeenLastCalledWith('zone-loading-door', {
      name: 'Dock door',
      points: [
        [0.08, 0.22],
        [0.42, 0.2],
        [0.44, 0.86],
        [0.06, 0.9],
      ],
    });
    expect(within(list).queryByText('Loading door')).toBeNull();
  });

  it('deletes a zone after an inline Yes / No confirmation', async () => {
    const { client, list } = await openZones();
    fireEvent.click(within(list).getByRole('button', { name: 'Delete Exit lane' }));
    expect(within(list).getByText('Delete Exit lane?')).toBeTruthy();
    fireEvent.click(within(list).getByRole('button', { name: 'No' }));
    expect(within(list).getByText('Exit lane')).toBeTruthy();

    fireEvent.click(within(list).getByRole('button', { name: 'Delete Exit lane' }));
    fireEvent.click(within(list).getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(within(list).queryByText('Exit lane')).toBeNull());
    expect((await client.listZones()).map((zone) => zone.name)).toEqual(['Loading door']);
  });

  it('normalises points to 0..1, clamps them and rounds to 4 decimals', () => {
    expect(normalisedPoint(100, 50, 400, 200)).toEqual([0.25, 0.25]);
    expect(normalisedPoint(-10, 500, 400, 200)).toEqual([0, 1]);
    expect(normalisedPoint(1, 1, 3, 3)).toEqual([0.3333, 0.3333]);
    expect(normalisedPoint(1, 2, 3, 0)).toBeNull();
    expect(nudge([0.99, 0.01], 0.05, -0.05)).toEqual([1, 0]);
  });
});
