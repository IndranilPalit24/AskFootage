// The Cameras page: tabs, summary cards, the registry table, status changes, delete (with the recordings
// confirmation), the Add new camera form and the 4-second refresh. Every test runs on the in-memory demo client.
import { act, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../web/src/api/client';
import type { Camera } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { deferred, renderApp } from './ui-test-utils';

const COST_TAIL = 'Indexing footage costs about $0.20 per 1,000 frames for each object type.';
const NOT_REFRESHED = 'Could not refresh. Retrying.';

async function openCameras(client = new MockApiClient()) {
  const view = renderApp('/cameras', client);
  await screen.findByRole('table');
  return view;
}

function table(): HTMLElement {
  return screen.getByRole('table');
}

function rowOf(name: string): HTMLElement {
  return within(table()).getByRole('cell', { name }).closest('tr')!;
}

function statusSelect(name: string): HTMLSelectElement {
  return screen.getByLabelText<HTMLSelectElement>(`Status of ${name}`);
}

function cardValue(label: string): string {
  return screen.getByText(label, { selector: 'dt' }).nextElementSibling!.textContent!;
}

function bodyRows(): HTMLElement[] {
  return within(table()).getAllByRole('row').slice(1);
}

function cellTexts(row: HTMLElement): string[] {
  return within(row).getAllByRole('cell').map((cell) => cell.textContent ?? '');
}

function openAddTab(): void {
  fireEvent.click(screen.getByRole('tab', { name: 'Add new camera' }));
}

function field(label: RegExp): HTMLInputElement {
  return screen.getByLabelText<HTMLInputElement>(label);
}

function type(label: RegExp, value: string): void {
  fireEvent.change(field(label), { target: { value } });
}

function fillValid(): void {
  type(/^Camera name/, 'Yard');
  type(/^Camera IP address or host/, '192.168.1.50');
  type(/^Stream username/, 'cam-user');
  type(/^Stream password/, 'hunter2-secret');
}

function acknowledge(): void {
  fireEvent.click(screen.getByRole('checkbox', { name: 'I understand that searching footage uses my Meta credits' }));
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: 'Add camera' }) as HTMLButtonElement;
}

function openDeleteDialog(name: string): HTMLElement {
  fireEvent.click(screen.getByRole('button', { name: `Delete ${name}` }));
  return screen.getByRole('dialog');
}

/** The seed's cameras with one extra that has no recordings, so it deletes at once. */
async function clientWithEmptyCamera() {
  const client = new MockApiClient();
  const added = await client.addCamera({
    name: 'Yard',
    ip: '192.168.1.50',
    username: 'u',
    password: 'p',
    acknowledgeCost: true,
  });
  return { client, id: added.id };
}

afterEach(() => {
  vi.useRealTimers();
  Reflect.deleteProperty(document, 'hidden');
});

describe('Cameras page: tabs', () => {
  it('has a tablist with two tabs and a tabpanel for the selected one', async () => {
    await openCameras();
    expect(screen.getByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
    const tablist = screen.getByRole('tablist');
    const tabs = within(tablist).getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Camera registry', 'Add new camera']);
    expect(tabs.map((tab) => tab.getAttribute('aria-selected'))).toEqual(['true', 'false']);
    expect(tabs.map((tab) => tab.getAttribute('tabindex'))).toEqual(['0', '-1']);
    const panel = screen.getByRole('tabpanel');
    expect(panel.getAttribute('aria-labelledby')).toBe(tabs[0].id);
    expect(tabs[0].getAttribute('aria-controls')).toBe(panel.id);
    expect(within(panel).getByRole('table')).toBeTruthy();
  });

  it('clicking a tab shows its panel and hides the other', async () => {
    await openCameras();
    openAddTab();
    expect(screen.getByRole('tab', { name: 'Add new camera' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByRole('tabpanel').contains(field(/^Camera name/))).toBe(true);
    fireEvent.click(screen.getByRole('tab', { name: 'Camera registry' }));
    expect(screen.getByRole('table')).toBeTruthy();
  });

  it('moves between tabs with the arrow, Home and End keys, focusing the new tab', async () => {
    await openCameras();
    const registry = screen.getByRole('tab', { name: 'Camera registry' });
    const add = screen.getByRole('tab', { name: 'Add new camera' });
    registry.focus();
    fireEvent.keyDown(registry, { key: 'ArrowRight' });
    expect(add.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(add);
    fireEvent.keyDown(add, { key: 'ArrowRight' }); // wraps around
    expect(registry.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(registry);
    fireEvent.keyDown(registry, { key: 'ArrowLeft' }); // wraps backwards
    expect(add.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(add, { key: 'Home' });
    expect(registry.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(registry, { key: 'End' });
    expect(add.getAttribute('aria-selected')).toBe('true');
  });
});

describe('Cameras page: summary cards and table', () => {
  it('shows the four summary cards computed from the list', async () => {
    await openCameras();
    expect(cardValue('Total cameras')).toBe('3');
    expect(cardValue('Online')).toBe('1');
    expect(cardValue('Standby')).toBe('1');
    expect(cardValue('Offline/Error')).toBe('1');
  });

  it('updates the cards after a status change', async () => {
    await openCameras();
    fireEvent.change(statusSelect('Front gate'), { target: { value: 'offline' } });
    await screen.findByText('Front gate is now Offline.');
    expect(cardValue('Total cameras')).toBe('3');
    expect(cardValue('Online')).toBe('1');
    expect(cardValue('Standby')).toBe('0');
    expect(cardValue('Offline/Error')).toBe('2');
  });

  it('has the columns ID, Name, Location, Zone, Department, Status and Actions', async () => {
    await openCameras();
    const headers = within(table()).getAllByRole('columnheader');
    expect(headers.map((header) => header.textContent)).toEqual([
      'ID',
      'Name',
      'Location',
      'Zone',
      'Department',
      'Status',
      'Actions',
    ]);
  });

  it('lists each camera with its zone count, and "Not set" for a missing location or department', async () => {
    await openCameras();
    const rows = bodyRows().map((row) => cellTexts(row).slice(0, 5));
    expect(rows).toEqual([
      ['CAM-001', 'Loading dock', 'Warehouse, north side', '2 zones', 'Logistics'],
      ['CAM-002', 'Front gate', 'Main entrance', '1 zone', 'Security'],
      ['CAM-003', 'Back door', 'Not set', 'No zones', 'Facilities'],
    ]);
  });

  it('shows "Not set" for a missing department too', async () => {
    const client = new MockApiClient();
    const real = client.listCameras.bind(client);
    client.listCameras = async () => (await real()).map((camera) => ({ ...camera, department: null }));
    await openCameras(client);
    expect(cellTexts(bodyRows()[0])[4]).toBe('Not set');
  });

  it('shows the status as a dot with a text label, never the dot alone', async () => {
    await openCameras();
    const cases: Array<[string, string, string]> = [
      ['Loading dock', 'Online', 'online'],
      ['Front gate', 'Standby', 'standby'],
      ['Back door', 'Offline', 'offline'],
    ];
    for (const [name, label, tone] of cases) {
      const cell = within(rowOf(name)).getAllByRole('cell')[5];
      const text = cell.querySelector('.cam-status__label')!;
      expect(text.textContent).toBe(label);
      const dot = cell.querySelector('.cam-dot')!;
      expect(dot.className).toContain(`cam-dot--${tone}`);
      expect(dot.getAttribute('aria-hidden')).toBe('true');
      expect(dot.textContent).toBe('');
    }
  });

  it('shows the loading text until the cameras arrive, and no table or cards', async () => {
    const client = new MockApiClient();
    const held = deferred<Camera[]>();
    const real = client.listCameras.bind(client);
    client.listCameras = () => held.promise;
    renderApp('/cameras', client);
    expect(await screen.findByText('Loading cameras…')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    held.resolve(await real());
    await screen.findByRole('table');
    expect(screen.queryByText('Loading cameras…')).toBeNull();
  });

  it('says what to do when there are no cameras', async () => {
    const client = new MockApiClient();
    client.listCameras = async () => [];
    renderApp('/cameras', client);
    expect(await screen.findByText('No cameras yet. Add one in the Add new camera tab.')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(cardValue('Total cameras')).toBe('0');
  });
});

describe('Cameras page: status dropdown', () => {
  it('changes the status through the API and says so', async () => {
    const { client } = await openCameras();
    const update = vi.spyOn(client, 'updateCamera');
    expect(statusSelect('Front gate').value).toBe('standby');
    expect(within(statusSelect('Front gate')).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Online',
      'Standby',
      'Offline',
    ]);
    fireEvent.change(statusSelect('Front gate'), { target: { value: 'online' } });
    expect(update).toHaveBeenCalledWith('CAM-002', { status: 'online' });
    expect(await screen.findByText('Front gate is now Online.')).toBeTruthy();
    expect(within(rowOf('Front gate')).getByText('Online', { selector: '.cam-status__label' })).toBeTruthy();
    expect((await client.getCamera('CAM-002')).status).toBe('online');
  });

  it('shows the new status at once, then rolls back with an error toast when the call fails', async () => {
    const { client } = await openCameras();
    const held = deferred<Camera>();
    client.updateCamera = () => held.promise;
    fireEvent.change(statusSelect('Front gate'), { target: { value: 'offline' } });
    // Optimistic: the label and the dropdown already say Offline.
    expect(statusSelect('Front gate').value).toBe('offline');
    expect(within(rowOf('Front gate')).getByText('Offline', { selector: '.cam-status__label' })).toBeTruthy();
    held.reject(new ApiError(500, 'internal_error', 'The server could not answer. Try again.'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not change the status of Front gate.');
    expect(alert.textContent).toContain('The server could not answer. Try again.');
    expect(statusSelect('Front gate').value).toBe('standby');
    expect(within(rowOf('Front gate')).getByText('Standby', { selector: '.cam-status__label' })).toBeTruthy();
    expect(cardValue('Standby')).toBe('1');
  });
});

describe('Cameras page: Recordings action', () => {
  it('links to the camera recordings', async () => {
    await openCameras();
    const links = within(table()).getAllByRole('link', { name: 'Recordings' });
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/cameras/CAM-001/recordings',
      '/cameras/CAM-002/recordings',
    ]);
    fireEvent.click(links[1]);
    expect(await screen.findByRole('heading', { level: 1, name: 'Recordings' })).toBeTruthy();
    expect(screen.getByText("Front gate · each day's recordings")).toBeTruthy();
  });

  it('is disabled for an offline camera, with a visible note, and does not navigate', async () => {
    await openCameras();
    const row = rowOf('Back door');
    expect(within(row).queryByRole('link')).toBeNull();
    const button = within(row).getByRole('button', { name: 'Recordings' });
    expect(button.getAttribute('aria-disabled')).toBe('true');
    const note = within(row).getByText('Offline: no recordings to open');
    expect(button.getAttribute('aria-describedby')).toContain(note.id);
    fireEvent.click(button);
    expect(screen.getByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 1, name: 'Recordings' })).toBeNull();
  });

  it('becomes available again when the camera is brought back online', async () => {
    await openCameras();
    fireEvent.change(statusSelect('Back door'), { target: { value: 'online' } });
    await screen.findByText('Back door is now Online.');
    const link = within(rowOf('Back door')).getByRole('link', { name: 'Recordings' });
    expect(link.getAttribute('href')).toBe('/cameras/CAM-003/recordings');
    expect(screen.queryByText('Offline: no recordings to open')).toBeNull();
  });
});

describe('Cameras page: delete', () => {
  it('asks first, in a dialog that takes focus, and Cancel keeps the camera', async () => {
    const { client } = await openCameras();
    const del = vi.spyOn(client, 'deleteCamera');
    const trigger = screen.getByRole('button', { name: 'Delete Loading dock' });
    trigger.focus();
    const dialog = openDeleteDialog('Loading dock');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(within(dialog).getByText('Delete Loading dock?')).toBeTruthy();
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(del).not.toHaveBeenCalled();
    expect(rowOf('Loading dock')).toBeTruthy();
    expect(document.activeElement).toBe(trigger);
  });

  it('Escape closes the dialog and gives focus back to the trash button', async () => {
    await openCameras();
    const trigger = screen.getByRole('button', { name: 'Delete Front gate' });
    trigger.focus();
    const dialog = openDeleteDialog('Front gate');
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(rowOf('Front gate')).toBeTruthy();
  });

  it('keeps Tab inside the dialog', async () => {
    await openCameras();
    const dialog = openDeleteDialog('Front gate');
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    const confirm = within(dialog).getByRole('button', { name: 'Delete' });
    confirm.focus();
    fireEvent.keyDown(confirm, { key: 'Tab' });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(cancel, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(confirm);
  });

  it('removes the row at once, then keeps it removed when the camera had no recordings', async () => {
    const { client, id } = await clientWithEmptyCamera();
    await openCameras(client);
    const held = deferred<void>();
    const del = vi.fn(() => held.promise);
    client.deleteCamera = del;
    fireEvent.click(within(openDeleteDialog('Yard')).getByRole('button', { name: 'Delete' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(within(table()).queryByRole('cell', { name: 'Yard' })).toBeNull(); // optimistic
    expect(cardValue('Total cameras')).toBe('3');
    expect(del).toHaveBeenCalledWith(id);
    held.resolve();
    expect(await screen.findByText('Deleted Yard.')).toBeTruthy();
    expect(within(table()).queryByRole('cell', { name: 'Yard' })).toBeNull();
    // The trash button is gone, so focus lands somewhere sensible instead of on <body>.
    expect(document.activeElement?.tagName).toBe('MAIN');
  });

  it('brings the row back with an error toast when the delete fails', async () => {
    const { client } = await clientWithEmptyCamera();
    await openCameras(client);
    const held = deferred<void>();
    client.deleteCamera = () => held.promise;
    fireEvent.click(within(openDeleteDialog('Yard')).getByRole('button', { name: 'Delete' }));
    expect(within(table()).queryByRole('cell', { name: 'Yard' })).toBeNull();
    held.reject(new ApiError(500, 'internal_error', 'The server could not answer. Try again.'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not delete Yard.');
    expect(within(table()).getByRole('cell', { name: 'Yard' })).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(cardValue('Total cameras')).toBe('4');
  });

  it('asks a second question when the camera has recordings, then deletes with deleteRecordings', async () => {
    const { client } = await openCameras();
    const del = vi.spyOn(client, 'deleteCamera');
    fireEvent.click(within(openDeleteDialog('Loading dock')).getByRole('button', { name: 'Delete' }));
    expect(del).toHaveBeenCalledWith('CAM-001');

    const second = await screen.findByRole('dialog');
    // The row is back, and the server's own counts message is on screen.
    expect(within(table()).getByRole('cell', { name: 'Loading dock' })).toBeTruthy();
    expect(
      within(second).getByText(
        'This camera has 18 recordings and 0 saved clips. Deleting it would delete them too; confirm to delete the camera together with its recordings.',
      ),
    ).toBeTruthy();
    expect(second.contains(document.activeElement)).toBe(true);
    expect(screen.queryByRole('alert')).toBeNull();

    fireEvent.click(within(second).getByRole('button', { name: 'Delete camera and its recordings' }));
    expect(del).toHaveBeenLastCalledWith('CAM-001', { deleteRecordings: true });
    expect(within(table()).queryByRole('cell', { name: 'Loading dock' })).toBeNull(); // optimistic again
    expect(await screen.findByText('Deleted Loading dock and its recordings.')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();

    const cameras = await client.listCameras();
    expect(cameras.map((camera) => camera.id)).toEqual(['CAM-002', 'CAM-003']);
    expect(await client.listRecordings('2026-10-30')).not.toEqual([]); // other cameras keep theirs
    expect((await client.listRecordings('2026-10-30')).every((recording) => recording.camera !== 'CAM-001')).toBe(true);
  });

  it('Cancel in the second dialog leaves the camera and its recordings alone', async () => {
    const { client } = await openCameras();
    const del = vi.spyOn(client, 'deleteCamera');
    fireEvent.click(within(openDeleteDialog('Front gate')).getByRole('button', { name: 'Delete' }));
    const second = await screen.findByRole('dialog');
    fireEvent.click(within(second).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(del).toHaveBeenCalledTimes(1);
    expect(rowOf('Front gate')).toBeTruthy();
    expect((await client.getCamera('CAM-002')).recordingCount).toBe(3);
  });

  it('brings the row back with an error toast when the second delete fails', async () => {
    const { client } = await openCameras();
    const real = client.deleteCamera.bind(client);
    client.deleteCamera = (id, options) =>
      options?.deleteRecordings ? Promise.reject(new Error('boom')) : real(id, options);
    fireEvent.click(within(openDeleteDialog('Front gate')).getByRole('button', { name: 'Delete' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Delete camera and its recordings' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not delete Front gate.');
    expect(rowOf('Front gate')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('Cameras page: Add new camera form', () => {
  it('has the six fields, a password field that hides what is typed, and a disabled button', async () => {
    await openCameras();
    openAddTab();
    for (const label of [
      /^Camera name/,
      /^Camera IP address or host/,
      /^Stream username/,
      /^Stream password/,
      /^Location\/Zone/,
      /^Department/,
    ]) {
      expect(field(label)).toBeTruthy();
    }
    expect(field(/^Stream password/).type).toBe('password');
    expect(field(/^Camera name/).required).toBe(true);
    expect(field(/^Location\/Zone/).required).toBe(false);
    expect(submitButton().disabled).toBe(true);
  });

  it('explains a problem under its field once the field has been left', async () => {
    await openCameras();
    openAddTab();
    expect(screen.queryByText('Enter a name for the camera.')).toBeNull(); // nothing shouted before any input
    fireEvent.blur(field(/^Camera name/));
    expect(screen.getByText('Enter a name for the camera.')).toBeTruthy();
    expect(field(/^Camera name/).getAttribute('aria-invalid')).toBe('true');
    const hint = document.getElementById(field(/^Camera name/).getAttribute('aria-describedby')!.split(' ')[0]);
    expect(hint?.textContent).toBe('Enter a name for the camera.');

    fireEvent.blur(field(/^Camera IP address or host/));
    expect(screen.getByText("Enter the camera's IP address.")).toBeTruthy();
    type(/^Camera IP address or host/, 'http://cam');
    expect(screen.getByText(/Enter an IPv4 address such as 192\.168\.1\.20/)).toBeTruthy();
    type(/^Camera IP address or host/, '192.168.1.50');
    expect(screen.queryByText(/Enter an IPv4 address/)).toBeNull();

    fireEvent.blur(field(/^Stream username/));
    expect(screen.getByText('Enter the stream username.')).toBeTruthy();
    fireEvent.blur(field(/^Stream password/));
    expect(screen.getByText('Enter the stream password.')).toBeTruthy();
    type(/^Camera name/, 'x'.repeat(81));
    expect(screen.getByText('Use at most 80 characters.')).toBeTruthy();
  });

  it('previews the stream address with the password masked and never renders the password', async () => {
    await openCameras();
    openAddTab();
    expect(screen.getByText('rtsp://<username>:****@<ip>:554/cam/realmonitor?channel=1&subtype=1')).toBeTruthy();
    fillValid();
    expect(screen.getByText('rtsp://cam-user:****@192.168.1.50:554/cam/realmonitor?channel=1&subtype=1')).toBeTruthy();
    expect(document.body.textContent).not.toContain('hunter2-secret');
    expect(document.body.innerHTML).not.toContain('hunter2-secret');
  });

  it('shows the cost note with the number of cameras registered', async () => {
    await openCameras();
    openAddTab();
    expect(screen.getByText(`3 cameras registered. ${COST_TAIL}`)).toBeTruthy();
  });

  it('uses the singular for one camera', async () => {
    const client = new MockApiClient();
    const real = client.listCameras.bind(client);
    client.listCameras = async () => (await real()).slice(0, 1);
    await openCameras(client);
    openAddTab();
    expect(screen.getByText(`1 camera registered. ${COST_TAIL}`)).toBeTruthy();
  });

  it('keeps Add camera disabled until every required field is valid and the cost box is ticked', async () => {
    await openCameras();
    openAddTab();
    fillValid();
    expect(submitButton().disabled).toBe(true); // not acknowledged yet
    acknowledge();
    expect(submitButton().disabled).toBe(false);
    type(/^Camera IP address or host/, 'not a host');
    expect(submitButton().disabled).toBe(true);
    type(/^Camera IP address or host/, 'cam-yard.local');
    expect(submitButton().disabled).toBe(false);
    acknowledge(); // unticked again
    expect(submitButton().disabled).toBe(true);
  });

  it('adds the camera: sends the body once, toasts, clears the form and shows the registry', async () => {
    const { client } = await openCameras();
    const add = vi.spyOn(client, 'addCamera');
    openAddTab();
    fillValid();
    type(/^Location\/Zone/, ' Yard east ');
    acknowledge();
    fireEvent.click(submitButton());
    expect(add).toHaveBeenCalledTimes(1);
    expect(add).toHaveBeenCalledWith({
      name: 'Yard',
      ip: '192.168.1.50',
      username: 'cam-user',
      password: 'hunter2-secret',
      location: 'Yard east',
      department: null,
      acknowledgeCost: true,
    });
    expect(await screen.findByText('Added Yard.')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Camera registry' }).getAttribute('aria-selected')).toBe('true');
    expect(cellTexts(rowOf('Yard')).slice(0, 5)).toEqual(['CAM-004', 'Yard', 'Yard east', 'No zones', 'Not set']);
    expect(cardValue('Total cameras')).toBe('4');

    openAddTab();
    for (const label of [/^Camera name/, /^Camera IP address or host/, /^Stream username/, /^Stream password/, /^Location\/Zone/]) {
      expect(field(label).value).toBe('');
    }
    expect(screen.getByRole<HTMLInputElement>('checkbox').checked).toBe(false);
    expect(submitButton().disabled).toBe(true);
    expect(screen.getByText(`4 cameras registered. ${COST_TAIL}`)).toBeTruthy();
    expect(document.body.innerHTML).not.toContain('hunter2-secret');
  });

  it('shows the server message under the name field when the name is taken', async () => {
    await openCameras();
    openAddTab();
    fillValid();
    type(/^Camera name/, 'loading DOCK');
    acknowledge();
    fireEvent.click(submitButton());
    const message = await screen.findByText('A camera called loading DOCK already exists.');
    const name = field(/^Camera name/);
    expect(name.getAttribute('aria-describedby')).toContain(message.id);
    expect(name.getAttribute('aria-invalid')).toBe('true');
    // The form stays as it was, on the same tab, so the name can be fixed.
    expect(screen.getByRole('tab', { name: 'Add new camera' }).getAttribute('aria-selected')).toBe('true');
    expect(field(/^Camera IP address or host/).value).toBe('192.168.1.50');
    // Editing the name clears the message.
    type(/^Camera name/, 'Loading dock 2');
    expect(screen.queryByText('A camera called loading DOCK already exists.')).toBeNull();
  });

  it('keeps the form and toasts when adding fails for another reason', async () => {
    const { client } = await openCameras();
    client.addCamera = () => Promise.reject(new ApiError(500, 'internal_error', 'The server could not answer. Try again.'));
    openAddTab();
    fillValid();
    acknowledge();
    fireEvent.click(submitButton());
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not add the camera.');
    expect(alert.textContent).toContain('The server could not answer. Try again.');
    expect(field(/^Camera name/).value).toBe('Yard');
    expect(submitButton().disabled).toBe(false);
  });

  it('has no face, identity or live-video feature', async () => {
    await openCameras();
    expect(document.body.textContent).not.toMatch(/face|identity|live view|live feed/i);
    expect(document.querySelector('video')).toBeNull();
  });
});

describe('Cameras page: refresh every 4 seconds', () => {
  /** Real timers for the first load, then the 4-second timer is the only fake. */
  async function openWithFakeInterval(client: MockApiClient) {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    const view = renderApp('/cameras', client);
    await screen.findByRole('table');
    return view;
  }

  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  function setHidden(hidden: boolean) {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
    document.dispatchEvent(new Event('visibilitychange'));
  }

  it('fetches the list again every 4 seconds and shows what changed, without a reload', async () => {
    const client = new MockApiClient();
    const list = vi.spyOn(client, 'listCameras');
    await openWithFakeInterval(client);
    expect(list).toHaveBeenCalledTimes(1);
    await advance(3999);
    expect(list).toHaveBeenCalledTimes(1);
    await client.addCamera({ name: 'Yard', ip: '10.0.0.9', username: 'u', password: 'p', acknowledgeCost: true });
    await advance(1);
    expect(list).toHaveBeenCalledTimes(2);
    expect(within(table()).getByRole('cell', { name: 'Yard' })).toBeTruthy();
    expect(cardValue('Total cameras')).toBe('4');
    await advance(4000);
    expect(list).toHaveBeenCalledTimes(3);
  });

  it('pauses while the page is hidden and refreshes at once when it is visible again', async () => {
    const client = new MockApiClient();
    const list = vi.spyOn(client, 'listCameras');
    await openWithFakeInterval(client);
    setHidden(true);
    await advance(20000);
    expect(list).toHaveBeenCalledTimes(1);
    setHidden(false);
    await advance(0);
    expect(list).toHaveBeenCalledTimes(2);
    await advance(4000);
    expect(list).toHaveBeenCalledTimes(3);
  });

  it('stops when the page is left', async () => {
    const client = new MockApiClient();
    const list = vi.spyOn(client, 'listCameras');
    const { unmount } = await openWithFakeInterval(client);
    unmount();
    await advance(20000);
    expect(list).toHaveBeenCalledTimes(1);
    setHidden(false); // a late visibility event does nothing either
    await advance(0);
    expect(list).toHaveBeenCalledTimes(1);
  });

  it('never starts a second fetch while one is still in flight', async () => {
    const client = new MockApiClient();
    const real = client.listCameras.bind(client);
    const held = deferred<Camera[]>();
    let calls = 0;
    client.listCameras = () => {
      calls += 1;
      return calls === 2 ? held.promise : real();
    };
    await openWithFakeInterval(client);
    await advance(4000);
    expect(calls).toBe(2);
    await advance(12000);
    expect(calls).toBe(2);
    held.resolve(await real());
    await advance(0);
    await advance(4000);
    expect(calls).toBe(3);
  });

  it('keeps the last list and shows one calm line when a refresh fails, with no toast', async () => {
    const client = new MockApiClient();
    const real = client.listCameras.bind(client);
    let failing = false;
    client.listCameras = () => (failing ? Promise.reject(new Error('offline')) : real());
    await openWithFakeInterval(client);
    expect(screen.queryByText(NOT_REFRESHED)).toBeNull();
    failing = true;
    await advance(4000);
    await advance(4000);
    await advance(4000);
    expect(screen.getAllByText(NOT_REFRESHED)).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryAllByTestId('toast')).toHaveLength(0);
    expect(bodyRows()).toHaveLength(3);
    expect(cardValue('Total cameras')).toBe('3');
    failing = false;
    await advance(4000);
    expect(screen.queryByText(NOT_REFRESHED)).toBeNull();
    expect(bodyRows()).toHaveLength(3);
  });

  it('does not let an old refresh undo a status change that is still being saved', async () => {
    const client = new MockApiClient();
    const real = client.listCameras.bind(client);
    const staleAnswer = deferred<Camera[]>();
    let calls = 0;
    client.listCameras = () => {
      calls += 1;
      return calls === 2 ? staleAnswer.promise : real();
    };
    await openWithFakeInterval(client);
    const before = await real();
    await advance(4000); // refresh number 2 is now in flight
    fireEvent.change(statusSelect('Front gate'), { target: { value: 'online' } });
    await advance(0);
    staleAnswer.resolve(before); // it still says Standby
    await advance(0);
    expect(statusSelect('Front gate').value).toBe('online');
  });
});
