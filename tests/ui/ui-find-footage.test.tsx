import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../web/src/api/errors';
import { MockApiClient } from '../../web/src/api/mockClient';
import { deferred, renderApp, waitForBoot } from './ui-test-utils';

async function openFindFootage(client = new MockApiClient()) {
  const view = renderApp('/', client);
  await waitForBoot();
  const box = await screen.findByLabelText<HTMLTextAreaElement>('Ask about the footage');
  return { ...view, box };
}

function pickDay(day: string) {
  fireEvent.change(screen.getByLabelText('Day:'), { target: { value: day } });
}

function ask(box: HTMLTextAreaElement, question: string) {
  fireEvent.change(box, { target: { value: question } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
}

function resultCards(): HTMLElement[] {
  return within(screen.getByRole('list', { name: 'Results' })).getAllByRole('article');
}

describe('Find Footage', () => {
  it('first visit: a large multi-line ask box, example chips and the scope line for today', async () => {
    const { box } = await openFindFootage();
    expect(screen.getByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect(box.tagName).toBe('TEXTAREA');
    expect(box.getAttribute('rows')).toBe('3');
    expect(box.getAttribute('placeholder')).toBe('Find your footage… e.g. someone carrying a box');
    const examples = within(screen.getByRole('list', { name: 'Example questions' })).getAllByRole('button');
    expect(examples.map((button) => button.textContent)).toEqual([
      'someone carrying a box',
      'anyone in the loading door',
      'someone waiting by the exit lane',
      'people carrying boxes through the loading door',
    ]);
    const day = screen.getByLabelText<HTMLSelectElement>('Day:');
    expect(day.value).toBe('2026-10-30');
    expect([...day.options].map((option) => option.textContent)).toEqual([
      'Sat 24 Oct',
      'Sun 25 Oct',
      'Mon 26 Oct',
      'Tue 27 Oct',
      'Wed 28 Oct',
      'Thu 29 Oct',
      'Fri 30 Oct',
    ]);
    expect(screen.getByText('Camera: Loading dock')).toBeTruthy();
    expect(screen.getByText('Ask about anything the camera saw. Each result shows the clip and why it matched.')).toBeTruthy();
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Search' }).disabled).toBe(true);
  });

  it('an example chip fills the box without sending', async () => {
    const client = new MockApiClient();
    const search = vi.spyOn(client, 'search');
    const { box } = await openFindFootage(client);
    fireEvent.click(screen.getByRole('button', { name: 'anyone in the loading door' }));
    expect(box.value).toBe('anyone in the loading door');
    expect(document.activeElement).toBe(box);
    expect(search).not.toHaveBeenCalled();
  });

  it('searching: the loading line names the day, then the clip cards show the evidence', async () => {
    const client = new MockApiClient();
    const held = deferred<void>();
    const realSearch = client.search.bind(client);
    const search = vi.spyOn(client, 'search').mockImplementation(async (request) => {
      await held.promise;
      return realSearch(request);
    });
    const { box } = await openFindFootage(client);
    pickDay('2026-10-29');
    fireEvent.click(screen.getByRole('button', { name: 'someone carrying a box' }));
    fireEvent.keyDown(box, { key: 'Enter' });

    const loading = screen.getByText("Searching Thu 29 Oct's footage…");
    expect(loading.closest('[aria-live="polite"]')).toBeTruthy();
    expect(search).toHaveBeenCalledWith({ question: 'someone carrying a box', day: '2026-10-29', camera: 'loading-dock' });

    held.resolve();
    expect(await screen.findByText('5 clips')).toBeTruthy();
    // The indexing recording is reported, not silently skipped.
    expect(screen.getByText('1 recording on this day is still being indexed, so it was not searched.')).toBeTruthy();
    expect(resultCards()).toHaveLength(5);
    const card = screen.getByRole('article', { name: 'Person carrying a box through the loading dock' });
    expect(within(card).getByText('10:42:15–10:42:31')).toBeTruthy();
    const chips = within(within(card).getByRole('list', { name: 'Evidence' })).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['Carrying · 16 s', 'In Loading door · 11 s']);
    expect(within(card).getByRole('link', { name: 'Open' }).getAttribute('href')).toBe('/clip/clip-1029-104215');
    expect(within(card).getByRole('button', { name: 'Save clip' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('Enter sends, Shift+Enter keeps writing, and a blank question is never sent', async () => {
    const client = new MockApiClient();
    const search = vi.spyOn(client, 'search');
    const { box } = await openFindFootage(client);

    fireEvent.change(box, { target: { value: '   ' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Search' }).disabled).toBe(true);

    fireEvent.change(box, { target: { value: 'someone waiting' } });
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(search).not.toHaveBeenCalled();

    fireEvent.keyDown(box, { key: 'Enter' });
    expect(search).toHaveBeenCalledWith({ question: 'someone waiting', day: '2026-10-30', camera: 'loading-dock' });
    expect(await screen.findByText('1 clip')).toBeTruthy();
  });

  it('says so when nothing matched, with the server note', async () => {
    const { box } = await openFindFootage();
    pickDay('2026-10-29');
    ask(box, 'a bicycle');
    expect(await screen.findByText('No clips matched on Thu 29 Oct. Try other words or another day.')).toBeTruthy();
    expect(screen.getByText(/Nothing in the question was recognised/)).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Results' })).toBeNull();
  });

  it('shows the error with Try again, which asks the same question again and recovers', async () => {
    const client = new MockApiClient();
    const realSearch = client.search.bind(client);
    const search = vi
      .spyOn(client, 'search')
      .mockRejectedValueOnce(new ApiError(500, 'internal_error', 'The search could not run. Try again.'))
      .mockImplementation((request) => realSearch(request));
    const { box } = await openFindFootage(client);
    pickDay('2026-10-29');
    ask(box, 'someone carrying a box');
    expect(await screen.findByText('The search could not run. Try again.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('5 clips')).toBeTruthy();
    expect(search).toHaveBeenCalledTimes(2);
    expect(search.mock.calls[1][0]).toEqual(search.mock.calls[0][0]);
  });

  it('changing the day asks the last question again for the new day', async () => {
    const { box } = await openFindFootage();
    ask(box, 'someone carrying a box');
    expect(await screen.findByText('1 clip')).toBeTruthy();
    pickDay('2026-10-29');
    expect(within(screen.getByRole('banner')).getByText('Thu 29 Oct')).toBeTruthy();
    expect(await screen.findByText('5 clips')).toBeTruthy();
  });

  it('"Back to results" from a clip shows the last search again', async () => {
    const { box } = await openFindFootage();
    pickDay('2026-10-29');
    ask(box, 'someone carrying a box');
    await screen.findByText('5 clips');
    fireEvent.click(within(resultCards()[3]).getByRole('link', { name: 'Open' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Person carrying a box through the loading dock' }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('link', { name: 'Back to results' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect(screen.getByText('5 clips')).toBeTruthy();
    expect(resultCards()).toHaveLength(5);
    expect(screen.getByLabelText<HTMLTextAreaElement>('Ask about the footage').value).toBe('someone carrying a box');
  });
});
