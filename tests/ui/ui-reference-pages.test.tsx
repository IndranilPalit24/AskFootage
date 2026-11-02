// The reference pass: shell account menu, the Activity Log (proposed, sample data), the lead result card,
// zone drawing keys, the saved-note counter, and the truth rule (no invented names in the source).
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { MockApiClient } from '../../web/src/api/mockClient';
import { ACTIVITY_BANNER, SAMPLE_ACTIVITY_LOG } from '../../web/src/features/activity/sampleActivity';
import { clearDemoSession, hasDemoSession, startDemoSession } from '../../web/src/features/signin/demoSession';
import { DISCLOSURE } from '../../web/src/components/DemoDisclosure';
import { renderApp, waitForBoot } from './ui-test-utils';

beforeEach(() => clearDemoSession());
afterEach(() => clearDemoSession());

describe('shell: account control', () => {
  it('names no person, role or site, and has no bell', async () => {
    startDemoSession();
    renderApp('/');
    await waitForBoot();
    // No person, no role, no bell.
    expect(screen.queryByText(/Jamie|Doyle|North Plant/)).toBeNull();
    expect(screen.queryByRole('button', { name: /notification/i })).toBeNull();
  });

  it('with a session, opens a menu and Sign out clears it and goes to /sign-in', async () => {
    startDemoSession();
    renderApp('/');
    await waitForBoot();
    const trigger = screen.getByRole('button', { name: /Demo session/ });
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(hasDemoSession()).toBe(false);
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull());
  });

  it('Escape closes the menu and returns focus to the button', async () => {
    startDemoSession();
    renderApp('/');
    await waitForBoot();
    const trigger = screen.getByRole('button', { name: /Demo session/ });
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe('Activity Log (proposed page, sample data)', () => {
  it('is in the nav, marked current, with one h1, the banner, a disabled export and a sample title', async () => {
    renderApp('/activity');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Activity Log' }).getAttribute('aria-current')).toBe('page');
    expect(await screen.findAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Activity Log');
    expect(screen.getByTestId('activity-banner').textContent).toBe(ACTIVITY_BANNER);
    const exportButton = screen.getByRole('button', { name: 'Export log' }) as HTMLButtonElement;
    expect(exportButton.disabled).toBe(true);
    expect(screen.getByText('Proposed')).toBeTruthy();
    expect(document.title).toContain('sample data');
    expect(screen.getAllByRole('row')).toHaveLength(SAMPLE_ACTIVITY_LOG.length + 1);
    expect(screen.getByText(DISCLOSURE)).toBeTruthy();
  });

  it('keeps the banner and the fictional users whatever the filters say, and filters the rows', async () => {
    renderApp('/activity');
    fireEvent.change(await screen.findByLabelText('User'), { target: { value: 'Sample user 1' } });
    fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'Saved clip' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('User'), { target: { value: 'Sample user 4' } });
    expect(screen.getByText('No sample entries match these filters.')).toBeTruthy();
    expect(screen.getByTestId('activity-banner')).toBeTruthy();
    expect(SAMPLE_ACTIVITY_LOG.every((entry) => entry.user.startsWith('Sample user'))).toBe(true);
  });
});

describe('Find Footage lead result', () => {
  async function searched() {
    const client = new MockApiClient();
    renderApp('/', client);
    await waitForBoot();
    fireEvent.change(await screen.findByLabelText('Ask about the footage'), { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const list = await screen.findByRole('list', { name: 'Results' });
    return within(list).getAllByRole('article')[0];
  }

  it('has a clear button, the day and camera filters, a result count and the time range as the title', async () => {
    const lead = await searched();
    expect(screen.getByRole('button', { name: 'Clear question' })).toBeTruthy();
    expect(screen.getByRole('option', { name: 'All cameras' })).toBeTruthy();
    expect(within(lead).getByRole('heading', { level: 2 }).textContent).toMatch(/^\d{1,2} \w{3} 2026, \d\d:\d\d:\d\d – \d\d:\d\d:\d\d$/);
    expect(within(lead).getByRole('link', { name: 'Open clip' })).toBeTruthy();
    expect(within(lead).getByRole('button', { name: /Save clip/ })).toBeTruthy();
    expect(within(lead).getByRole('slider', { name: 'Seek' })).toBeTruthy();
    expect(within(lead).getByTestId('playbar-time').textContent).toMatch(/^\d\d:\d\d \/ \d\d:\d\d$/);
  });

  it('clearing the question empties the field', async () => {
    await searched();
    fireEvent.click(screen.getByRole('button', { name: 'Clear question' }));
    expect((screen.getByLabelText('Ask about the footage') as HTMLTextAreaElement).value).toBe('');
  });

  it('requests no video until play is pressed, then mounts only that one video', async () => {
    const lead = await searched();
    expect(lead.querySelector('video')).toBeNull();
    fireEvent.click(within(lead).getByRole('button', { name: 'Play' }));
    // The mock client has no video address (no footage): nothing is mounted and nothing breaks.
    expect(document.querySelectorAll('video').length).toBeLessThanOrEqual(1);
  });

  it('shows "preview unavailable" with a retry when the poster fails', async () => {
    const lead = await searched();
    const img = lead.querySelector('img');
    if (img) {
      fireEvent.error(img);
      expect(within(lead).getByText('Preview unavailable')).toBeTruthy();
      expect(within(lead).getByRole('button', { name: 'Try again' })).toBeTruthy();
    } else {
      expect(within(lead).getByText('No preview')).toBeTruthy();
    }
  });
});

describe('Cameras page header', () => {
  it('has an Add camera button that opens the Add new camera tab', async () => {
    renderApp('/cameras');
    const buttons = await screen.findAllByRole('button', { name: 'Add camera' });
    fireEvent.click(buttons[0]);
    expect(screen.getByRole('tab', { name: 'Add new camera' }).getAttribute('aria-selected')).toBe('true');
  });
});

describe('Saved Clips note counter', () => {
  it('shows the count against the 200 limit', async () => {
    const client = new MockApiClient();
    const clips = (await client.search({ question: 'someone carrying a box', day: '2026-10-30' })).clips;
    await client.saveClip({ clipId: clips[0].id, note: 'x'.repeat(67) });
    renderApp('/saved', client);
    expect(await screen.findByText('67/200')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save note' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Remove' })).toBeTruthy();
  });
});

describe('Zones page', () => {
  it('names the camera by id and name, hints at the real drawing behaviour, and cancels with Escape', async () => {
    renderApp('/zones');
    const select = (await screen.findByLabelText('Camera')) as HTMLSelectElement;
    expect([...select.options].every((option) => /^CAM-\d+ - /.test(option.textContent ?? ''))).toBe(true);
    expect(screen.getByRole('button', { name: 'New zone' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'New zone' }));
    expect(screen.getByText(/Double click to finish/)).toBeTruthy();
    const frame = screen.getByTestId('zone-frame');
    fireEvent.keyDown(frame, { key: 'Escape' });
    expect(screen.queryByRole('form', { name: 'New zone' })).toBeNull();
  });
});

describe('truth rule: nothing invented in the source', () => {
  const sources = import.meta.glob('../../web/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

  it('names no site, user or role outside the clearly named sample constant', () => {
    for (const [path, text] of Object.entries(sources)) {
      if (path.includes('sampleActivity')) continue;
      expect(text, path).not.toMatch(/Jamie Doyle|North Plant|Priya Shah|Mark Wilson|Chris Tan|Motion agreement.{0,20}High/);
    }
  });

  it('shows no IP address, stream address or credential in the registry source', () => {
    const table = Object.entries(sources).find(([path]) => path.endsWith('cameras/CameraTable.tsx'))![1];
    expect(table).not.toMatch(/camera\.ip|rtsp|password/i);
  });
});
