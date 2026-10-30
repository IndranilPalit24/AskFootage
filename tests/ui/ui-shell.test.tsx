import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MockApiClient } from '../../web/src/api/mockClient';
import { DRAWER_STORAGE_KEY } from '../../web/src/app/AppShell';
import { renderApp, waitForBoot } from './ui-test-utils';

describe('app shell: topbar and drawer', () => {
  it('shows the brand, the server today (last entry of /api/days) and the Demo data chip', async () => {
    renderApp('/');
    await waitForBoot();
    const banner = screen.getByRole('banner');
    expect(within(banner).getByRole('link', { name: 'AskFootage' }).getAttribute('href')).toBe('/');
    expect(within(banner).getByText('Fri 30 Oct')).toBeTruthy();
    expect(within(banner).getByText('Demo data')).toBeTruthy();
  });

  it('has no Demo data chip when the server is not in demo mode', async () => {
    renderApp('/', new MockApiClient({ demoMode: false }));
    await waitForBoot();
    expect(screen.queryByText('Demo data')).toBeNull();
  });

  it('lists the screens in the reference order, with their hints, and marks the current one', async () => {
    renderApp('/camera');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual(['Find Footage', 'Camera', 'Zones', 'Saved clips']);
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/', '/camera', '/zones', '/saved']);
    expect(links.map((link) => link.getAttribute('title'))).toEqual([
      'Ask a question about your footage',
      "Each day's recordings",
      'Mark areas of the camera view',
      'Clips you kept as evidence',
    ]);
    expect(within(nav).getByRole('link', { name: 'Camera' }).getAttribute('aria-current')).toBe('page');
    expect(within(nav).getByRole('link', { name: 'Find Footage' }).getAttribute('aria-current')).toBeNull();
    await waitForBoot();
  });

  it('collapses to icons: names stay for screen readers, aria attributes toggle, the choice is remembered', async () => {
    renderApp('/');
    await waitForBoot();
    const toggle = screen.getByRole('button', { name: 'Hide menu names' });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.getAttribute('aria-controls')).toBe(nav.id);
    expect(nav.classList.contains('drawer--collapsed')).toBe(false);
    expect(within(nav).getByText('Camera').classList.contains('visually-hidden')).toBe(false);
    expect(within(nav).getByText('Powered by Meta')).toBeTruthy();

    fireEvent.click(toggle);

    expect(toggle.getAttribute('aria-label')).toBe('Show menu names');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(nav.classList.contains('drawer--collapsed')).toBe(true);
    // Hidden from sight, still the link's accessible name.
    expect(within(nav).getByText('Camera').classList.contains('visually-hidden')).toBe(true);
    expect(within(nav).getByRole('link', { name: 'Camera' })).toBeTruthy();
    expect(within(nav).queryByText('Powered by Meta')).toBeNull();
    expect(window.localStorage.getItem(DRAWER_STORAGE_KEY)).toBe('1');

    fireEvent.click(screen.getByRole('button', { name: 'Show menu names' }));

    expect(toggle.getAttribute('aria-label')).toBe('Hide menu names');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(within(nav).getByText('Powered by Meta')).toBeTruthy();
    expect(window.localStorage.getItem(DRAWER_STORAGE_KEY)).toBe('0');
  });

  it('starts collapsed when it was collapsed last time', async () => {
    window.localStorage.setItem(DRAWER_STORAGE_KEY, '1');
    renderApp('/');
    await waitForBoot();
    expect(screen.getByRole('button', { name: 'Show menu names' }).getAttribute('aria-expanded')).toBe('false');
  });

  it('names no model anywhere and offers a skip link to the content', async () => {
    renderApp('/');
    await waitForBoot();
    expect(document.body.textContent).not.toMatch(/llama|muse|\bsam\b|segment anything|gpt|claude|gemini/i);
    const skip = screen.getByRole('link', { name: 'Skip to content' });
    expect(document.getElementById(skip.getAttribute('href')!.slice(1))?.tagName).toBe('MAIN');
  });

  it('shows the error and Try again when the status cannot be loaded', async () => {
    const client = new MockApiClient();
    let calls = 0;
    const realStatus = client.getStatus.bind(client);
    client.getStatus = () => {
      calls += 1;
      return calls === 1 ? Promise.reject(new Error('offline')) : realStatus();
    };
    renderApp('/', client);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Something went wrong. Try again.');
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await waitForBoot();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
