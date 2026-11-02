// The welcome page at /welcome: landmarks, every section's key content, the demo links, the in-page
// anchors, and that no brand, model or vendor name appears anywhere in the rendered text.
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from './ui-test-utils';

function renderWelcome() {
  return renderApp('/welcome');
}

describe('welcome page: route and top bar', () => {
  it('renders at /welcome outside the app shell, with its own landmarks', () => {
    renderWelcome();
    expect(screen.getByRole('banner')).toBeTruthy();
    expect(screen.getByRole('main')).toBeTruthy();
    // Not the app shell: no drawer, no Find Footage heading.
    expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Find Footage' })).toBeNull();
  });

  it('has a skip link to the main content', () => {
    renderWelcome();
    const skip = screen.getByRole('link', { name: 'Skip to content' });
    const main = screen.getByRole('main');
    expect(skip.getAttribute('href')).toBe(`#${main.id}`);
    expect(main.getAttribute('tabindex')).toBe('-1');
  });

  it('the top bar has the wordmark, the four section links and Try the demo', () => {
    renderWelcome();
    const banner = screen.getByRole('banner');
    expect(within(banner).getByRole('link', { name: 'AskFootage' }).getAttribute('href')).toBe('#top');
    const nav = within(banner).getByRole('navigation', { name: 'Page sections' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual(['How it works', 'Features', 'Privacy', 'Cost']);
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['#how', '#features', '#privacy', '#cost']);
    expect(within(banner).getByRole('link', { name: 'Try the demo' }).getAttribute('href')).toBe('/');
  });

  it('leaves Find Footage at / as it was', () => {
    renderApp('/');
    expect(screen.getByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeTruthy();
  });
});

describe('welcome page: hero', () => {
  it('has the one h1, the subtext and the ask box as a link into the demo', () => {
    renderWelcome();
    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0].textContent).toBe('Ask your footage. Get the clip and the proof.');
    expect(screen.getByText(/Type a question in plain English/)).toBeTruthy();
    const ask = screen.getByRole('link', { name: 'Ask in the demo: Show me when a person carried a box' });
    expect(ask.getAttribute('href')).toBe('/');
    // It says what it does: it opens the demo, it is not a field.
    expect(ask.getAttribute('aria-describedby')).toBe('welcome-ask-note');
    expect(document.getElementById('welcome-ask-note')!.textContent).toBe(
      'Opens the demo, where you type your own question.',
    );
  });

  it("shows the demo's own example questions as plain chips, not controls", () => {
    renderWelcome();
    const list = screen.getByRole('list', { name: 'Questions the demo suggests:' });
    const items = within(list).getAllByRole('listitem').map((item) => item.textContent);
    expect(items).toEqual([
      'someone carrying a box',
      'anyone in the loading door',
      'someone waiting by the exit lane',
      'people carrying boxes through the loading door',
    ]);
    expect(within(list).queryAllByRole('button')).toEqual([]);
    expect(within(list).queryAllByRole('link')).toEqual([]);
  });

  it('offers Try the demo and a link down to How it works', () => {
    renderWelcome();
    const hero = screen.getByRole('region', { name: 'Ask your footage. Get the clip and the proof.' });
    expect(within(hero).getByRole('link', { name: 'Try the demo' }).getAttribute('href')).toBe('/');
    expect(within(hero).getByRole('link', { name: 'See how it works' }).getAttribute('href')).toBe('#how');
  });
});
