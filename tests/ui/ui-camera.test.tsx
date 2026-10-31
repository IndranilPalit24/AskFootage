import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Recording } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { deferred, renderApp } from './ui-test-utils';

const FRI_30_SUMMARY = '4 recordings · 7 h · 2 ready';
const THU_29_SUMMARY = '6 recordings · 2 h 14 min · 5 ready';
/** CAM-001 is the Loading dock camera in the demo seed. */
const RECORDINGS = '/cameras/CAM-001/recordings';

/** The cells of each body row: start time, length, status, action. */
function rowTexts(): string[][] {
  const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
  return rows.map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent ?? ''));
}

function dayButton(name: string): HTMLElement {
  return within(screen.getByRole('group', { name: 'Day' })).getByRole('button', { name });
}

async function openCamera(client = new MockApiClient()) {
  const view = renderApp(RECORDINGS, client);
  await screen.findByText(FRI_30_SUMMARY);
  return view;
}

describe('Camera recordings screen', () => {
  it('has the reference page head, the seven days with today selected, and the table headers', async () => {
    await openCamera();
    expect(screen.getByRole('heading', { level: 1, name: 'Recordings' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'All cameras' }).getAttribute('href')).toBe('/cameras');
    expect(screen.getByText("Loading dock · each day's recordings")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add footage' })).toBeTruthy();
    const days = within(screen.getByRole('group', { name: 'Day' })).getAllByRole('button');
    expect(days.map((day) => day.textContent)).toEqual(['Sat 24', 'Sun 25', 'Mon 26', 'Tue 27', 'Wed 28', 'Thu 29', 'Fri 30']);
    expect(days.map((day) => day.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'false', 'false', 'false', 'false', 'true']);
    // The summary is a polite live region, so a new day is announced.
    expect(screen.getByText(FRI_30_SUMMARY).getAttribute('aria-live')).toBe('polite');
    const headers = within(screen.getByRole('table')).getAllByRole('columnheader');
    expect(headers.map((header) => header.textContent)).toEqual(['Start time', 'Length', 'Status', 'Actions']);
    expect(within(headers[3]).getByText('Actions').classList.contains('visually-hidden')).toBe(true);
  });

  it('picking Thu 29 changes the list, the summary and the topbar date', async () => {
    await openCamera();
    fireEvent.click(dayButton('Thu 29'));
    expect(await screen.findByText(THU_29_SUMMARY)).toBeTruthy();
    expect(dayButton('Thu 29').getAttribute('aria-pressed')).toBe('true');
    expect(dayButton('Fri 30').getAttribute('aria-pressed')).toBe('false');
    expect(rowTexts().map((cells) => cells.slice(0, 3))).toEqual([
      ['06:00:00', '31 min', 'Ready'],
      ['07:05:00', '24 min', 'Ready'],
      ['09:12:00', '18 min', 'Ready'],
      ['10:30:00', '27 min', 'Ready'],
      ['13:00:00', '22 min', 'Ready'],
      ['16:10:00', '12 min', 'Indexing'],
    ]);
    expect(within(screen.getByRole('banner')).getByText('Thu 29 Oct')).toBeTruthy();
  });

  it('gives ready rows a small Open button and the others their note', async () => {
    await openCamera();
    expect(rowTexts().map((cells) => cells.slice(2))).toEqual([
      ['Ready', 'Open'],
      ['Ready', 'Open'],
      ['Preparing', 'Almost there'],
      ['Waiting', 'Not uploaded yet'],
    ]);

    fireEvent.click(dayButton('Thu 29'));
    await screen.findByText(THU_29_SUMMARY);
    expect(rowTexts().map((cells) => cells[3])).toEqual(['Open', 'Open', 'Open', 'Open', 'Open', 'Nearly searchable']);
    const open = screen.getAllByRole('link', { name: 'Open' })[0];
    expect(open.className).toBe('btn btn--sm');
    // Each Open is described by its row's start time.
    expect(document.getElementById(open.getAttribute('aria-describedby')!)?.textContent).toBe('06:00:00');
    expect(screen.getAllByText('Ready')[0].className).toBe('status status--ready');
    expect(screen.getByText('Indexing').className).toBe('status');
  });

  it('Open goes to Find Footage, scoped to the same day', async () => {
    await openCamera();
    fireEvent.click(dayButton('Thu 29'));
    await screen.findByText(THU_29_SUMMARY);
    fireEvent.click(screen.getAllByRole('link', { name: 'Open' })[2]);
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect((await screen.findByLabelText<HTMLSelectElement>('Day:')).value).toBe('2026-10-29');
  });

  it('has the footer note, whose link asks about this day', async () => {
    await openCamera();
    fireEvent.click(dayButton('Wed 28'));
    await screen.findByText('3 recordings · 6 h · 3 ready');
    const link = screen.getByRole('link', { name: 'Ask a question about this day' });
    expect(link.closest('p')?.textContent).toBe('Ready recordings can be searched from Find Footage. Ask a question about this day');
    fireEvent.click(link);
    expect((await screen.findByLabelText<HTMLSelectElement>('Day:')).value).toBe('2026-10-28');
  });

  it('shows an empty day calmly', async () => {
    await openCamera();
    fireEvent.click(dayButton('Sun 25'));
    expect(await screen.findByText('No recordings on this day.')).toBeTruthy();
    expect(screen.getByText('No recordings')).toBeTruthy();
  });

  it('shows "Loading recordings…", then a load error with Try again that recovers', async () => {
    const client = new MockApiClient();
    const first = deferred<Recording[]>();
    let calls = 0;
    const realList = client.listRecordings.bind(client);
    client.listRecordings = (day, camera) => {
      calls += 1;
      return calls === 1 ? first.promise : realList(day, camera);
    };
    renderApp(RECORDINGS, client);
    expect(await screen.findAllByText('Loading recordings…')).toHaveLength(2); // summary line and table row
    first.reject(new Error('offline'));
    expect(await screen.findByText('Something went wrong. Try again.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText(FRI_30_SUMMARY)).toBeTruthy();
  });

  it('Add footage opens the file picker', async () => {
    await openCamera();
    const input = screen.getByLabelText<HTMLInputElement>('Footage file (MP4)');
    expect(input.getAttribute('accept')).toBe('video/mp4');
    const click = vi.spyOn(input, 'click').mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Add footage' }));
    expect(click).toHaveBeenCalledTimes(1);
  });

  it('uploads an MP4 to the selected day, then refreshes the list and the summary', async () => {
    const client = new MockApiClient();
    const upload = vi.spyOn(client, 'addRecording');
    await openCamera(client);
    fireEvent.click(dayButton('Sun 25'));
    await screen.findByText('No recordings on this day.');

    const file = new File(['fake'], 'dock.mp4', { type: 'video/mp4' });
    fireEvent.change(screen.getByLabelText('Footage file (MP4)'), { target: { files: [file] } });

    expect(upload).toHaveBeenCalledWith(file, '2026-10-25', 'CAM-001');
    expect(await screen.findByText('Added dock.mp4. It is waiting to be processed.')).toBeTruthy();
    // A new upload has no length yet, so the summary leaves the length out.
    expect(await screen.findByText('1 recording · 0 ready')).toBeTruthy();
    expect(rowTexts()).toEqual([['00:00:00', '—', 'Waiting', 'Not uploaded yet']]);
  });

  it('explains a refused file inline', async () => {
    await openCamera();
    fireEvent.change(screen.getByLabelText('Footage file (MP4)'), {
      target: { files: [new File(['x'], 'notes.txt', { type: 'text/plain' })] },
    });
    expect(await screen.findByText('Only MP4 video files can be added.')).toBeTruthy();
    expect(screen.getByText(FRI_30_SUMMARY)).toBeTruthy();
  });
});
