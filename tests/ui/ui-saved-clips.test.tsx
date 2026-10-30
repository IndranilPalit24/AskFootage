import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MockApiClient } from '../../web/src/api/mockClient';
import { renderApp, waitForBoot } from './ui-test-utils';

const DOCK_CLIP = 'Person carrying a box through the loading dock';

function goTo(label: string) {
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: label }));
}

/** Asks "someone carrying a box" about Thu 29; the loading-dock clip is the 4th of 5. */
async function searchThursday(): Promise<HTMLElement[]> {
  const box = await screen.findByLabelText('Ask about the footage');
  fireEvent.change(screen.getByLabelText('Day:'), { target: { value: '2026-10-29' } });
  fireEvent.change(box, { target: { value: 'someone carrying a box' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByText('5 clips');
  return within(screen.getByRole('list', { name: 'Results' })).getAllByRole('article');
}

describe('Save clip and the Saved clips screen', () => {
  it('saves a result and unsaves it again; the Saved clips screen follows', async () => {
    const { client } = renderApp('/');
    await waitForBoot();
    const card = (await searchThursday())[3];
    const button = within(card).getByRole('button', { name: 'Save clip' });
    expect(button.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute('aria-pressed')).toBe('true'));
    expect(button.textContent).toBe('Saved');
    expect((await client.listSavedClips()).map((saved) => saved.clip.id)).toEqual(['clip-1029-104215']);

    goTo('Saved clips');
    const list = await screen.findByRole('list', { name: 'Saved clips' });
    const row = within(list).getByRole('article', { name: DOCK_CLIP });
    expect(within(row).getByText('Thu 29 Oct · 10:42:15')).toBeTruthy();
    expect(within(row).getByRole('link', { name: 'Open' }).getAttribute('href')).toBe('/clip/clip-1029-104215');

    // Back on the restored results, unsave it from the same button.
    goTo('Find Footage');
    const again = within(screen.getByRole('list', { name: 'Results' })).getAllByRole('article')[3];
    const saved = within(again).getByRole('button', { name: 'Saved' });
    fireEvent.click(saved);
    await waitFor(() => expect(saved.getAttribute('aria-pressed')).toBe('false'));
    expect(saved.textContent).toBe('Save clip');
    expect(await client.listSavedClips()).toEqual([]);

    goTo('Saved clips');
    expect(await screen.findByText('No saved clips yet. Use Save clip on any result to keep it here.')).toBeTruthy();
  });

  it('the clip page and the result cards share one saved state', async () => {
    renderApp('/clip/clip-1029-104215');
    fireEvent.click(await screen.findByRole('button', { name: 'Save clip' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Saved' }).getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('link', { name: 'Back to results' }));
    const cards = await searchThursday();
    expect(within(cards[3]).getByRole('button', { name: 'Saved' }).getAttribute('aria-pressed')).toBe('true');
    expect(within(cards[0]).getByRole('button', { name: 'Save clip' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('starts empty and says how to save', async () => {
    renderApp('/saved');
    expect(screen.getByRole('heading', { level: 1, name: 'Saved clips' })).toBeTruthy();
    expect(await screen.findByText('No saved clips yet. Use Save clip on any result to keep it here.')).toBeTruthy();
  });

  it('edits the note (PATCH) and confirms it', async () => {
    const client = new MockApiClient();
    const saved = await client.saveClip({ clipId: 'clip-1029-104215', note: 'Check this delivery' });
    const update = vi.spyOn(client, 'updateSavedClip');
    renderApp('/saved', client);
    const row = await screen.findByRole('article', { name: DOCK_CLIP });
    const note = within(row).getByLabelText<HTMLTextAreaElement>('Note');
    expect(note.value).toBe('Check this delivery');
    expect(note.maxLength).toBe(500);

    fireEvent.change(note, { target: { value: 'Matches the paperwork' } });
    fireEvent.click(within(row).getByRole('button', { name: 'Save note' }));
    expect(await within(row).findByText('Note saved')).toBeTruthy();
    expect(update).toHaveBeenCalledWith(saved.id, { note: 'Matches the paperwork' });
    expect((await client.listSavedClips())[0].note).toBe('Matches the paperwork');
  });

  it('filters by day, with its own empty message', async () => {
    const client = new MockApiClient();
    await client.saveClip({ clipId: 'clip-1029-104215' });
    const list = vi.spyOn(client, 'listSavedClips');
    renderApp('/saved', client);
    await screen.findByRole('article', { name: DOCK_CLIP });
    const select = screen.getByLabelText<HTMLSelectElement>('Day');
    expect([...select.options].map((option) => option.textContent)).toEqual([
      'All days',
      'Sat 24 Oct',
      'Sun 25 Oct',
      'Mon 26 Oct',
      'Tue 27 Oct',
      'Wed 28 Oct',
      'Thu 29 Oct',
      'Fri 30 Oct',
    ]);

    fireEvent.change(select, { target: { value: '2026-10-28' } });
    expect(await screen.findByText('No saved clips from Wed 28 Oct.')).toBeTruthy();
    expect(list).toHaveBeenLastCalledWith('2026-10-28');

    fireEvent.change(select, { target: { value: '2026-10-29' } });
    expect(await screen.findByRole('article', { name: DOCK_CLIP })).toBeTruthy();
  });

  it('removes a saved clip, announces it and keeps the others', async () => {
    const client = new MockApiClient();
    await client.saveClip({ clipId: 'clip-1029-104215' });
    await client.saveClip({ clipId: 'clip-1030-065240', note: 'second' });
    renderApp('/saved', client);
    const list = await screen.findByRole('list', { name: 'Saved clips' });
    expect(within(list).getAllByRole('article')).toHaveLength(2);

    fireEvent.click(within(within(list).getByRole('article', { name: DOCK_CLIP })).getByRole('button', { name: 'Remove' }));

    await waitFor(() => expect(within(list).getAllByRole('article')).toHaveLength(1));
    expect(within(list).queryByRole('article', { name: DOCK_CLIP })).toBeNull();
    expect(screen.getByText(`Removed ${DOCK_CLIP}.`)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Saved clips' }));
    expect((await client.listSavedClips()).map((saved) => saved.clip.id)).toEqual(['clip-1030-065240']);
  });

  it('shows a load error with Try again', async () => {
    const client = new MockApiClient();
    let offline = true;
    const realList = client.listSavedClips.bind(client);
    client.listSavedClips = (day) => (offline ? Promise.reject(new Error('offline')) : realList(day));
    renderApp('/saved', client);
    expect(await screen.findByText('Something went wrong. Try again.')).toBeTruthy();
    offline = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('No saved clips yet. Use Save clip on any result to keep it here.')).toBeTruthy();
  });
});
