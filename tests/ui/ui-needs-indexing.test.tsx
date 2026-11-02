import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../web/src/api/errors';
import type { ConceptJob } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { renderApp, waitForBoot } from './ui-test-utils';

async function askAbout(client: MockApiClient, question = 'a forklift near the door') {
  renderApp('/', client);
  await waitForBoot();
  const box = await screen.findByLabelText<HTMLTextAreaElement>('Ask about the footage');
  fireEvent.change(box, { target: { value: question } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  return screen.findByRole('region', { name: 'Not searched yet for forklift' });
}

const job = (state: ConceptJob['state'], message: string | null = null): ConceptJob => ({
  noun: 'forklift',
  state,
  recordingIds: ['r1'],
  estimatedCostUsd: 0.06,
  message,
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Not searched yet panel', () => {
  it('shows the noun, the cost and a Search button that waits for the checkbox', async () => {
    const panel = await askAbout(new MockApiClient());
    expect(within(panel).getByRole('heading', { name: 'Not searched yet for forklift' })).toBeTruthy();
    expect(panel.textContent).toMatch(/\$\d+\.\d\d/);
    const button = within(panel).getByRole<HTMLButtonElement>('button', { name: 'Search for forklift' });
    expect(button.disabled).toBe(true);
    fireEvent.click(within(panel).getByRole('checkbox', { name: 'I accept this cost' }));
    expect(button.disabled).toBe(false);
  });

  it('is not shown when nothing is missing', async () => {
    renderApp('/', new MockApiClient());
    await waitForBoot();
    const box = await screen.findByLabelText<HTMLTextAreaElement>('Ask about the footage');
    fireEvent.change(box, { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByRole('list', { name: 'Results' });
    expect(screen.queryByText(/Not searched yet/)).toBeNull();
  });

  it('posts the concept with the searched day, polls every 2 s, then searches again', async () => {
    const client = new MockApiClient();
    const post = vi.spyOn(client, 'requestConcept');
    const get = vi.spyOn(client, 'getConcept');
    const search = vi.spyOn(client, 'search');
    const panel = await askAbout(client);
    expect(search).toHaveBeenCalledTimes(1);

    fireEvent.click(within(panel).getByRole('checkbox', { name: 'I accept this cost' }));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(panel).getByRole('button', { name: 'Search for forklift' }));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith({ noun: 'forklift', confirm: true, day: '2026-10-30' }));
    await within(panel).findByText('Waiting to start…');
    expect(get).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(2000));
    await within(panel).findByText('Searching the footage…');
    expect(get).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(2000));
    await vi.waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(get).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(screen.queryByText(/Not searched yet for forklift/)).toBeNull());
  });

  it('a failed pass shows its message and can be tried again', async () => {
    const client = new MockApiClient();
    const post = vi.spyOn(client, 'requestConcept').mockResolvedValue(job('queued'));
    vi.spyOn(client, 'getConcept').mockResolvedValue(job('failed', 'No saved result for that object.'));
    const panel = await askAbout(client);
    fireEvent.click(within(panel).getByRole('checkbox', { name: 'I accept this cost' }));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(panel).getByRole('button', { name: 'Search for forklift' }));
    await within(panel).findByText('Waiting to start…');
    await act(() => vi.advanceTimersByTimeAsync(2000));
    await within(panel).findByText('No saved result for that object.');
    post.mockClear();
    fireEvent.click(within(panel).getByRole('button', { name: 'Try again' }));
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
  });

  it.each([
    ['budget_exceeded', 409, /spending limit/],
    ['indexing_not_configured', 503, /not set up/],
  ])('says plainly what %s means and does not poll', async (code, status, text) => {
    const client = new MockApiClient();
    vi.spyOn(client, 'requestConcept').mockRejectedValue(new ApiError(status, code, 'raw server text'));
    const get = vi.spyOn(client, 'getConcept');
    const panel = await askAbout(client);
    fireEvent.click(within(panel).getByRole('checkbox', { name: 'I accept this cost' }));
    fireEvent.click(within(panel).getByRole('button', { name: 'Search for forklift' }));
    await waitFor(() => expect(panel.textContent).toMatch(text));
    expect(panel.textContent).not.toContain('raw server text');
    expect(get).not.toHaveBeenCalled();
  });

  it('keeps the status in a polite live region and uses no vendor or identity wording', async () => {
    const panel = await askAbout(new MockApiClient());
    expect(panel.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(panel.textContent).not.toMatch(/face|identity|recogni|meta|openai|gemini|claude|sam/i);
  });
});
